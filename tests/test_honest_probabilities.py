"""Honest probabilities: no code path may fill a null `p_model` with a
default.

Two complements: (1) a live-pipeline test proving `analyze()` itself never
invents a probability for a proposal that had none, and (2) a static scan
over the engine/board source tree for the textual SHAPES a silent default
would take (`p_model or <number>`, `p_model if p_model is not None else
<number>`, `.get("p_model", <number>)`, `p_model = 0.5`), so a future edit
that reintroduces one fails a test immediately rather than waiting to be
noticed in a report.
"""

from __future__ import annotations

import ast
import re
import textwrap
import unittest
from pathlib import Path

from src.board.ids import selection_id
from src.engine.analyze import (
    VALUE_BASIS_PRICE_STANDING_ONLY, analyze,
)
from src.engine.snapshot import PriceBlindSnapshot, PricedBoard
from src.board.record import PriceObservation
from src.engine.analyze import Proposal

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = (REPO_ROOT / "src" / "engine", REPO_ROOT / "src" / "board",
            REPO_ROOT / "src" / "accounts")

# Textual shapes a silent "fill p_model with a default" would take. Case
# matters (p_model is always this exact identifier); a numeric fallback is
# the tell -- `p_model or None` or `p_model if ... else None` is NOT a
# default (None stays None), so the forbidden patterns all end in a number.
_DEFAULT_PATTERNS = (
    re.compile(r"p_model\s+or\s+0(?!\w)"),
    re.compile(r"p_model\s+or\s+0\.\d"),
    re.compile(r"p_model\s+if\s+.*\selse\s+0(?:\.\d+)?\b"),
    re.compile(r'\.get\(\s*["\']p_model["\']\s*,\s*0(?:\.\d+)?\s*\)'),
    re.compile(r"p_model\s*=\s*0\.\d+\s*$", re.MULTILINE),
)


def _iter_py_files():
    for d in SCAN_DIRS:
        if d.exists():
            yield from d.rglob("*.py")


class TestNoStaticDefaultForPModel(unittest.TestCase):
    def test_no_forbidden_p_model_default_pattern_anywhere(self):
        offenders = []
        for path in _iter_py_files():
            text = path.read_text(encoding="utf-8")
            for pattern in _DEFAULT_PATTERNS:
                for m in pattern.finditer(text):
                    line_no = text[:m.start()].count("\n") + 1
                    offenders.append(f"{path}:{line_no}: {m.group(0)!r}")
        self.assertEqual(offenders, [],
                         f"found p_model default pattern(s): {offenders}")

    def test_trivial_system_and_evolab_adapter_never_default_p_model(self):
        """The two REAL production `AnalysisSystem`s in this repository:
        `TrivialAlwaysHomeSystem` states an honest FIXED p_model (never a
        default filled in for an absent one); `EvolabGenomeSystem` always
        reports `p_model=None` (checked directly on its own source, since a
        genome's `score` structurally cannot be projected onto one --
        src/engine/adapters/evolab_system.py's own docstring)."""
        import inspect

        from src.engine.adapters.evolab_system import EvolabGenomeSystem

        source = textwrap.dedent(inspect.getsource(EvolabGenomeSystem.propose))
        self.assertIn("p_model", source)
        # The adapter never assigns p_model to anything but the literal
        # absence -- it simply never appears as a Proposal kwarg at all,
        # which this asserts by parsing the AST and checking every
        # Proposal(...) call in the function has no p_model keyword (i.e.
        # it always defaults to the Proposal dataclass's own None).
        tree = ast.parse(source)
        proposal_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "Proposal"
        ]
        self.assertTrue(proposal_calls)
        for call in proposal_calls:
            kwarg_names = {kw.arg for kw in call.keywords}
            self.assertNotIn("p_model", kwarg_names,
                             "EvolabGenomeSystem.propose must never pass "
                             "p_model at all -- absence, not a default")


class TestAnalyzeNeverFabricatesAProbability(unittest.TestCase):
    """End-to-end: a real `analyze()` call, fed a proposal with no
    p_model, must come back with p_model still None, no Bet Rating, no
    edge_bps, and a named value_basis -- never a filled-in number anywhere
    on the resulting DecisionRecord."""

    def _board(self, game_pk="game1"):
        home_sel = selection_id(sport="mlb", market_key="h2h", side="home")
        away_sel = selection_id(sport="mlb", market_key="h2h", side="away")
        quotes = (
            PriceObservation(
                sport="mlb", event_id=game_pk, game_pk=None, market_key="h2h",
                selection_id=home_sel, side="home", subject_kind=None,
                subject_id=None, line=None, book="book_a", price_american=-150,
                observed_utc="2026-09-02T18:00:00Z", book_last_update=None,
                known_at="2026-09-02T18:00:00Z", known_at_grade="A",
                capture_id="c1", source="odds_api", region="us",
                provider_market_key="h2h", l0_available=False),
            PriceObservation(
                sport="mlb", event_id=game_pk, game_pk=None, market_key="h2h",
                selection_id=away_sel, side="away", subject_kind=None,
                subject_id=None, line=None, book="book_a", price_american=130,
                observed_utc="2026-09-02T18:00:00Z", book_last_update=None,
                known_at="2026-09-02T18:00:00Z", known_at_grade="A",
                capture_id="c2", source="odds_api", region="us",
                provider_market_key="h2h", l0_available=False),
        )
        return PricedBoard.from_price_observations(
            game_pk, "2026-09-02T18:00:00Z", quotes)

    def _snapshot(self, game_pk="game1"):
        return PriceBlindSnapshot(
            game_pk=game_pk, t="2026-09-02T18:00:00Z", point_class="LATE_BOARD",
            features={}, available_markets=("h2h",),
            books_by_market={"h2h": 1},
        )

    def test_null_p_model_survives_the_whole_pipeline_untouched(self):
        class NoProbabilitySystem:
            id = "no_probability"
            version = "1.0"
            spec_hash = "no_probability:1"
            declared_markets = ("h2h",)
            declared_inputs = ()
            min_grade = "D"
            expected_selection_rate = 1.0

            def propose(self, view):
                return (Proposal(system_id=self.id, system_version=self.version,
                                 market_key="h2h", side="home",
                                 thesis="directional, no calibrated p"),)

        board = self._board()
        snapshot = self._snapshot()
        analysis = analyze(snapshot, board, systems=(NoProbabilitySystem(),),
                           adversaries=())
        self.assertEqual(len(analysis.records), 1)
        record = analysis.records[0]
        self.assertIsNone(record.p_model)
        self.assertIsNone(record.rating)
        self.assertIsNone(record.edge_bps)
        self.assertIsNone(record.price_improvement_bps)
        self.assertEqual(record.value_basis, VALUE_BASIS_PRICE_STANDING_ONLY)

    def test_systems_that_do_carry_a_probability_are_unaffected(self):
        class ProbabilitySystem:
            id = "has_probability"
            version = "1.0"
            spec_hash = "has_probability:1"
            declared_markets = ("h2h",)
            declared_inputs = ()
            min_grade = "D"
            expected_selection_rate = 1.0

            def propose(self, view):
                return (Proposal(system_id=self.id, system_version=self.version,
                                 market_key="h2h", side="home", p_model=0.6,
                                 thesis="calibrated"),)

        board = self._board()
        snapshot = self._snapshot()
        analysis = analyze(snapshot, board, systems=(ProbabilitySystem(),),
                           adversaries=())
        self.assertEqual(len(analysis.records), 1)
        record = analysis.records[0]
        self.assertEqual(record.p_model, 0.6)
        self.assertIsNotNone(record.rating)
        self.assertIsNone(record.value_basis)


if __name__ == "__main__":
    unittest.main()
