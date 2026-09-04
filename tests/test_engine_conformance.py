import unittest

from src.engine.analyze import Proposal
from src.engine.conformance import run_conformance
from src.engine.snapshot import PriceBlindSnapshot


def _snapshot(game_pk="1", t="2026-04-11T20:00:00Z", **features):
    return PriceBlindSnapshot(
        game_pk=game_pk, t=t, point_class="LATE_BOARD",
        features=features, available_markets=("h2h",),
        books_by_market={"h2h": 3},
    )


class _HonestSystem:
    """Reads only its declared feature, proposes deterministically."""

    id = "honest"
    version = "1"
    spec_hash = "h"
    declared_markets = ("h2h",)
    declared_inputs = ("era",)
    min_grade = "D"
    expected_selection_rate = 0.0

    def propose(self, view):
        era = view.features.get("era")
        if era is None or era <= 0.5:
            return ()
        return (Proposal(
            system_id=self.id, system_version=self.version,
            market_key="h2h", side="home", p_model=0.6, p_model_provenance="model_derived",
            thesis="era high",
        ),)


class _PriceSneakingSystem(_HonestSystem):
    """Tries to read a forbidden price-shaped attribute."""

    id = "sneaky"

    def propose(self, view):
        _ = getattr(view, "board", None)
        return super().propose(view)


class _UndeclaredFeatureSystem(_HonestSystem):
    """Reads a feature it never declared."""

    id = "undeclared"
    declared_inputs = ()

    def propose(self, view):
        _ = view.features.get("era")
        return ()


class _NondeterministicSystem(_HonestSystem):
    """Different output on each call -- purity violation."""

    id = "flaky"

    def __init__(self):
        self._n = 0

    def propose(self, view):
        self._n += 1
        if self._n % 2 == 0:
            return (Proposal(system_id=self.id, system_version="1",
                              market_key="h2h", side="home", p_model=0.6,
                              p_model_provenance="model_derived"),)
        return ()


class _BadSchemaSystem(_HonestSystem):
    """Returns a malformed proposal."""

    id = "bad_schema"

    def propose(self, view):
        return (Proposal(system_id="", system_version="1",
                          market_key="h2h", side="sideways", p_model=1.5,
                          p_model_provenance="model_derived"),)


class TestConformancePasses(unittest.TestCase):
    def test_honest_system_passes_every_check(self):
        result = run_conformance(_HonestSystem(), [_snapshot(era=0.9)])
        self.assertTrue(result.passed, result.to_dict())
        names = {c.name for c in result.checks}
        self.assertEqual(
            names,
            {"purity", "price_blindness", "schema", "declared_inputs",
             "determinism"})
        for check in result.checks:
            self.assertTrue(check.passed, (check.name, check.reasons))


class TestConformanceCatchesEachDefect(unittest.TestCase):
    def test_price_sneaking_system_fails_price_blindness(self):
        result = run_conformance(_PriceSneakingSystem(), [_snapshot(era=0.9)])
        self.assertFalse(result.passed)
        by_name = {c.name: c for c in result.checks}
        self.assertFalse(by_name["price_blindness"].passed)

    def test_undeclared_feature_read_fails(self):
        result = run_conformance(_UndeclaredFeatureSystem(),
                                  [_snapshot(era=0.9)])
        self.assertFalse(result.passed)
        by_name = {c.name: c for c in result.checks}
        self.assertFalse(by_name["declared_inputs"].passed)
        self.assertTrue(
            any("era" in r for r in by_name["declared_inputs"].reasons))

    def test_nondeterministic_system_fails_purity(self):
        result = run_conformance(_NondeterministicSystem(),
                                  [_snapshot(era=0.9)])
        self.assertFalse(result.passed)
        by_name = {c.name: c for c in result.checks}
        self.assertFalse(by_name["purity"].passed)

    def test_bad_schema_system_fails_schema(self):
        result = run_conformance(_BadSchemaSystem(), [_snapshot(era=0.9)])
        self.assertFalse(result.passed)
        by_name = {c.name: c for c in result.checks}
        self.assertFalse(by_name["schema"].passed)

    def test_a_deliberately_leaky_system_fails_conformance_overall(self):
        """A system that is both price-sneaking AND reads undeclared
        features -- deliberately maximally leaky -- must fail overall, not
        merely on one check."""

        class _LeakySystem(_HonestSystem):
            id = "leaky"
            declared_inputs = ()

            def propose(self, view):
                _ = getattr(view, "prices", None)
                _ = view.features.get("era")
                return ()

        result = run_conformance(_LeakySystem(), [_snapshot(era=0.9)])
        self.assertFalse(result.passed)


class TestDeterminismAcrossRestart(unittest.TestCase):
    def test_restart_check_reproduces_hash_via_subprocess(self):
        result = run_conformance(
            _HonestSystem(), [_snapshot(era=0.9)],
            system_factory="tests.test_engine_conformance:_make_honest_system")
        by_name = {c.name: c for c in result.checks}
        self.assertTrue(by_name["determinism"].passed,
                         by_name["determinism"].reasons)
        self.assertTrue(
            any("fresh process" in r for r in by_name["determinism"].reasons))


def _make_honest_system():
    return _HonestSystem()


if __name__ == "__main__":
    unittest.main()
