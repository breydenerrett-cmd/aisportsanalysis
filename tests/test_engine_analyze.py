import ast
import inspect
import unittest

from src.board.record import PriceObservation
from src.engine.analyze import (
    Analysis, Candidate, Counterargument, FATAL, MINOR, Proposal, analyze,
)
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard


def _po(selection_id, side, price, book="fanduel", market_key="h2h"):
    return PriceObservation(
        sport="mlb", event_id="e1", game_pk=1, market_key=market_key,
        selection_id=selection_id, side=side, subject_kind=None,
        subject_id=None, line=None, book=book, price_american=price,
        observed_utc="2023-04-11T20:00:00Z", book_last_update=None,
        known_at="2023-04-11T20:00:00Z", known_at_grade="A",
        capture_id="c1", source="test", region="us",
        provider_market_key=market_key,
    )


HOME = "aaaaaaaaaaaaaaaa"
AWAY = "bbbbbbbbbbbbbbbb"


def _snapshot(**kw):
    base = dict(game_pk="1", t="2023-04-11T20:00:00Z",
                point_class="LATE_BOARD", features={})
    base.update(kw)
    return PriceBlindSnapshot(**base)


def _board():
    return PricedBoard.from_price_observations("1", "2023-04-11T20:00:00Z", (
        _po(HOME, "home", -150, book="a"),
        _po(AWAY, "away", 130, book="a"),
        _po(HOME, "home", -140, book="b"),
        _po(AWAY, "away", 120, book="b"),
    ))


class _RecordingSystem:
    """Sees only what it is handed; a test asserts it never receives board."""

    def __init__(self, proposals):
        self.id = "recording"
        self.version = "1"
        self.spec_hash = "h"
        self.declared_markets = ("h2h",)
        self.declared_inputs = ()
        self.min_grade = "D"
        self.expected_selection_rate = 0.0
        self._proposals = proposals
        self.seen = []

    def propose(self, view):
        self.seen.append(view)
        assert isinstance(view, PriceBlindSnapshot)
        return self._proposals


class TestPurity(unittest.TestCase):
    def test_analyze_reads_only_its_own_arguments(self):
        src = inspect.getsource(analyze)
        tree = ast.parse(src)
        banned_calls = {"open", "input", "random", "time", "datetime", "now"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(
                    node.func.id, banned_calls,
                    f"analyze() must not call {node.func.id}()")

    def test_deterministic_across_repeated_calls(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.62),))
        snap, board = _snapshot(), _board()
        a1 = analyze(snap, board, systems=(system,))
        a2 = analyze(snap, board, systems=(system,))
        self.assertEqual(
            [r.to_dict() for r in a1.records],
            [r.to_dict() for r in a2.records])


class TestPriceBlindness(unittest.TestCase):
    def test_system_never_receives_a_priced_board(self):
        system = _RecordingSystem(())
        analyze(_snapshot(), _board(), systems=(system,))
        self.assertEqual(len(system.seen), 1)
        seen = system.seen[0]
        with self.assertRaises(AttributeError):
            seen.board
        with self.assertRaises(AttributeError):
            seen.price


class TestProjection(unittest.TestCase):
    def test_proposal_projects_onto_matching_selection_and_computes_edge(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.70),))
        analysis = analyze(_snapshot(), _board(), systems=(system,))
        self.assertEqual(len(analysis.records), 1)
        rec = analysis.records[0]
        self.assertEqual(rec.selection_id, HOME)
        self.assertEqual(rec.verdict, "play")
        self.assertIsNotNone(rec.consensus_fair)
        self.assertIsNotNone(rec.edge_bps)
        self.assertEqual(rec.books_at_decision, 2)

    def test_projects_onto_every_matching_selection_when_multiple_lines(self):
        board = PricedBoard.from_price_observations("1", "t", (
            _po("s_over_1", "over", -110, market_key="totals"),
            _po("s_under_1", "under", -110, market_key="totals"),
            _po("s_over_2", "over", -105, market_key="totals"),
            _po("s_under_2", "under", -115, market_key="totals"),
        ))
        # Note: different selection_ids here stand in for different lines
        # (a real board keys on selection_id derived from the line, per
        # src/board/ids.py). This test only needs two "over" selections to
        # confirm one proposal is priced against BOTH.
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="totals",
            side="over", p_model=0.55),))
        # adversaries=() explicitly: this test is about PROJECT fanning one
        # proposal out onto every matching selection, not about ATTACK, and
        # each selection here is quoted by only one book -- ThinBoard (part
        # of analyze()'s now-default adversary roster) would FATAL-veto both
        # candidates otherwise, which is a different thing than what this
        # test checks.
        analysis = analyze(_snapshot(), board, systems=(system,), adversaries=())
        selections = {r.selection_id for r in analysis.records}
        self.assertEqual(selections, {"s_over_1", "s_over_2"})

    def test_no_proposals_is_empty_analysis(self):
        analysis = analyze(_snapshot(), _board(), systems=(_RecordingSystem(()),))
        self.assertEqual(analysis.records, ())


class _VetoAdversary:
    id = "veto_all"

    def attack(self, candidate, snapshot, board):
        return (Counterargument(adversary_id=self.id, cause="TEST_VETO",
                                severity=FATAL),)


class _MinorAdversary:
    id = "minor_note"

    def attack(self, candidate, snapshot, board):
        return (Counterargument(adversary_id=self.id, cause="NOTE",
                                severity=MINOR),)


class TestAdversaries(unittest.TestCase):
    def test_fatal_counterargument_removes_candidate(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        analysis = analyze(_snapshot(), _board(), systems=(system,),
                           adversaries=(_VetoAdversary(),))
        self.assertEqual(analysis.records, ())

    def test_minor_counterargument_survives_and_is_recorded(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        analysis = analyze(_snapshot(), _board(), systems=(system,),
                           adversaries=(_MinorAdversary(),))
        self.assertEqual(len(analysis.records), 1)
        self.assertEqual(len(analysis.records[0].counterarguments), 1)
        self.assertEqual(
            analysis.records[0].counterarguments[0]["severity"], MINOR)


class TestTwoLedger(unittest.TestCase):
    def test_probability_and_price_quality_are_separate_numbers(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.9),))
        analysis = analyze(_snapshot(), _board(), systems=(system,))
        rating = analysis.records[0].rating
        self.assertIn("probability_quality", rating)
        self.assertIn("price_quality", rating)
        self.assertNotEqual(
            rating["probability_quality"], rating["price_quality"])

    def test_rating_dict_never_uses_the_label_edge(self):
        """The RATE-phase output dict keys are probability/price quality,
        never a key spelled "edge" -- edge_bps is a distinct PROJECT-phase
        field on DecisionRecord, not part of the Two-Ledger rating."""
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        analysis = analyze(_snapshot(), _board(), systems=(system,))
        for key in analysis.records[0].rating:
            self.assertNotIn("edge", key)


class TestProvenance(unittest.TestCase):
    def test_assumption_exposure_passes_through_to_record(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.6),))
        snap = _snapshot(assumption_exposure={"D:home_lineup": 1})
        analysis = analyze(snap, _board(), systems=(system,))
        self.assertEqual(
            analysis.records[0].assumption_exposure, {"D:home_lineup": 1})


class TestDeterministicOrdering(unittest.TestCase):
    def test_higher_edge_ranks_first(self):
        system = _RecordingSystem((
            Proposal(system_id="lo", system_version="1", market_key="h2h",
                    side="home", p_model=0.55),
            Proposal(system_id="hi", system_version="1", market_key="h2h",
                    side="home", p_model=0.95),
        ))
        analysis = analyze(_snapshot(), _board(), systems=(system,))
        self.assertEqual(analysis.records[0].system_id, "hi")
        self.assertEqual(analysis.records[1].system_id, "lo")


if __name__ == "__main__":
    unittest.main()
