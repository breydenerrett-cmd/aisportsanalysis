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
    def test_fatal_counterargument_removes_candidate_from_staking_but_publishes_it(self):
        """A FATAL veto must never make a candidate unreachable for
        staking, but it must ALSO never make the candidate vanish from
        `analysis.records` entirely (src/engine/analyze.py:250's old bug --
        the comment claimed 'recorded below as verdict=no_play' while the
        code silently dropped it). The refusal is published: verdict is a
        REFUSAL_VERDICTS member (never "play"), refusal_reason names the
        FATAL cause, and the FATAL counterargument is still attached."""
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        analysis = analyze(_snapshot(), _board(), systems=(system,),
                           adversaries=(_VetoAdversary(),))
        self.assertEqual(len(analysis.records), 1)
        record = analysis.records[0]
        self.assertNotEqual(record.verdict, "play")
        self.assertEqual(record.verdict, "no_play")  # no refused_* is
        # registered for the test-only "veto_all" adversary id
        self.assertEqual(record.refusal_reason, "TEST_VETO")
        fatal = [c for c in record.counterarguments if c["severity"] == FATAL]
        self.assertEqual(len(fatal), 1)
        self.assertEqual(fatal[0]["cause"], "TEST_VETO")

    def test_fatal_veto_by_a_registered_adversary_gets_its_own_verdict(self):
        """`stale_book`/`thin_board` FATAL vetoes get their specific
        `refused_stale`/`refused_thin` verdicts (src.ledger.records.VERDICTS)
        rather than the generic fallback -- so the EOD veto section can
        group and name them precisely."""
        from src.engine.adversaries import ThinBoard

        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        # `_board()` quotes each selection from 2 books; ThinBoard(min_books=3)
        # FATAL-vetoes everything at that depth.
        analysis = analyze(_snapshot(), _board(), systems=(system,),
                           adversaries=(ThinBoard(min_books=3),))
        self.assertEqual(len(analysis.records), 1)
        self.assertEqual(analysis.records[0].verdict, "refused_thin")
        self.assertIn("thin_board", analysis.records[0].refusal_reason)

    def test_minor_counterargument_survives_and_is_recorded(self):
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.7),))
        # assumption_exposure set (grade A on its own terms) so this test's
        # counterargument count isolates the adversary's own MINOR note from
        # the separate "no as_of read" counterargument analyze() adds when a
        # snapshot's grade is downgraded for having no read at all (see
        # TestProvenance below).
        snap = _snapshot(assumption_exposure={"A:x": 1})
        analysis = analyze(snap, _board(), systems=(system,),
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

    def test_no_asof_read_grades_d_not_a(self):
        """Regression for bug #1: an empty `assumption_exposure` with no
        as_of read (`asof_read=False`, the dataclass default) must NOT fail
        open to grade A -- there is zero evidence anything was graded at
        all. It must grade D and the record must carry a counterargument
        naming the missing read."""
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.6),))
        snap = _snapshot(assumption_exposure={})  # asof_read defaults False
        analysis = analyze(snap, _board(), systems=(system,))
        record = analysis.records[0]
        self.assertEqual(record.known_at_grade, "D")
        self.assertTrue(any(
            c["cause"].startswith("no_asof_read")
            for c in record.counterarguments))

    def test_asof_read_that_finds_nothing_still_grades_d(self):
        """Correction: `PriceBlindSnapshot.from_asof` folds EVERY observed
        as_of field into assumption_exposure regardless of its own grade
        (src/engine/snapshot.py), so an empty assumption_exposure can never
        mean "read some real fields, all grade A" -- it can only mean
        nothing was read at all. `asof_read=True` with an empty exposure is
        exactly that second case (a real as_of call happened but matched
        zero rows for this game_pk at this t, e.g. a 2023-24 game_pk against
        forward stores that did not exist yet) and must grade D, with the
        same counterargument family as the no-read case, not A. An earlier
        revision of this test asserted the opposite (grade A here) on the
        mistaken premise that empty exposure could mean "found zero
        degraded fields"; it cannot, for the reason above."""
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.6),))
        snap = _snapshot(assumption_exposure={}, asof_read=True)
        analysis = analyze(snap, _board(), systems=(system,))
        record = analysis.records[0]
        self.assertEqual(record.known_at_grade, "D")
        self.assertTrue(any(
            c["cause"].startswith("no_asof_read")
            for c in record.counterarguments))
        # The detail distinguishes "a read happened but found nothing" from
        # "no read happened at all" -- both grade D, for different reasons.
        detail = next(c["detail"] for c in record.counterarguments
                     if c["cause"].startswith("no_asof_read"))
        self.assertIn("matched zero fields", detail)

    def test_asof_read_with_real_grade_a_fields_earns_a(self):
        """The genuinely earned case: assumption_exposure carries real,
        grade-A field provenance (as `PriceBlindSnapshot.from_asof` produces
        when an as_of read actually found a field, at any grade) -- only
        this, never an empty exposure, is evidence enough for grade A."""
        system = _RecordingSystem((Proposal(
            system_id="s1", system_version="1", market_key="h2h",
            side="home", p_model=0.6),))
        snap = _snapshot(assumption_exposure={"A:home_plate_umpire": 1},
                         asof_read=True)
        analysis = analyze(snap, _board(), systems=(system,))
        record = analysis.records[0]
        self.assertEqual(record.known_at_grade, "A")
        self.assertFalse(any(
            c["cause"].startswith("no_asof_read")
            for c in record.counterarguments))


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
