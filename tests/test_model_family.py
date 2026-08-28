"""Tests for src/model/family.py.

The whole module is a defence against one failure: testing many things and
reporting only what survived. So the tests care most about the count being
frozen before results exist, and about the correction actually rejecting the
noise an uncorrected threshold would have promoted.
"""

import json
import random
import tempfile
import unittest
from pathlib import Path

from src.detect import base
from src.model import family


class FakeDetector:
    def __init__(self, name, markets, status=base.UNPROVEN):
        self.name = name
        self.markets = markets
        self.status = status


def registry(*detectors):
    return {d.name: d for d in detectors}


class TestEnumeration(unittest.TestCase):

    def test_a_detector_across_three_markets_is_three_hypotheses(self):
        # Eleven detectors is not eleven tests, and treating it as such is how a
        # family quietly becomes four times its stated size.
        found = family.enumerate_family(
            registry(FakeDetector("a", ("h2h", "totals", "h2h_1st_5_innings"))))
        self.assertEqual(len(found), 3)

    def test_blocked_detectors_are_excluded(self):
        # A blocked detector cannot produce a result, so counting it would make
        # the correction more conservative for no reason.
        found = family.enumerate_family(registry(
            FakeDetector("a", ("h2h",)),
            FakeDetector("b", ("h2h",), status=base.BLOCKED)))
        self.assertEqual([h["detector"] for h in found], ["a"])

    def test_enumeration_is_deterministic(self):
        detectors = registry(FakeDetector("b", ("h2h",)),
                             FakeDetector("a", ("h2h",)))
        self.assertEqual(family.enumerate_family(detectors),
                         family.enumerate_family(detectors))


class TestRegistrationIsFrozen(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "family.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_registering_writes_the_count(self):
        payload = family.register(registry(FakeDetector("a", ("h2h", "totals"))),
                                  path=self.path)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(self.path.exists())

    def test_re_registering_the_same_family_is_a_no_op(self):
        detectors = registry(FakeDetector("a", ("h2h",)))
        family.register(detectors, path=self.path)
        again = family.register(detectors, path=self.path)
        self.assertEqual(again["count"], 1)

    def test_adding_a_detector_afterwards_raises(self):
        # The count is the correction's input. Changing it silently invalidates
        # every p-value computed against the old one.
        family.register(registry(FakeDetector("a", ("h2h",))), path=self.path)
        with self.assertRaises(family.FamilyError) as ctx:
            family.register(registry(FakeDetector("a", ("h2h",)),
                                     FakeDetector("b", ("h2h",))),
                            path=self.path)
        self.assertIn("Added:", str(ctx.exception))

    def test_the_error_names_what_changed_in_both_directions(self):
        family.register(registry(FakeDetector("a", ("h2h",)),
                                 FakeDetector("b", ("h2h",))), path=self.path)
        with self.assertRaises(family.FamilyError) as ctx:
            family.register(registry(FakeDetector("a", ("h2h",)),
                                     FakeDetector("c", ("h2h",))),
                            path=self.path)
        message = str(ctx.exception)
        self.assertIn("'detector': 'c'", message.replace('"', "'"))
        self.assertIn("Removed:", message)

    def test_reading_before_registering_refuses_rather_than_defaulting(self):
        # A correction computed against a count chosen afterwards is not a
        # correction, so there is no sensible default to fall back to.
        with self.assertRaises(family.FamilyError) as ctx:
            family.read(self.path)
        self.assertIn("before running any evaluation", str(ctx.exception))


class TestBenjaminiHochberg(unittest.TestCase):

    def test_the_step_up_accepts_everything_below_the_cutoff(self):
        # Accepting each result independently is the classic implementation
        # error and rejects real effects that the step-up procedure keeps.
        results = [{"p": p} for p in (0.001, 0.02, 0.045, 0.6, 0.8)]
        corrected = family.benjamini_hochberg(results, q=0.10)
        self.assertEqual([c["survives_fdr"] for c in corrected],
                         [True, True, True, False, False])

    def test_nothing_survives_when_every_p_is_large(self):
        corrected = family.benjamini_hochberg([{"p": p} for p in (0.4, 0.6, 0.9)])
        self.assertFalse(any(c["survives_fdr"] for c in corrected))

    def test_results_are_returned_sorted_with_their_thresholds(self):
        corrected = family.benjamini_hochberg([{"p": 0.5}, {"p": 0.01}])
        self.assertEqual([c["p"] for c in corrected], [0.01, 0.5])
        self.assertEqual(corrected[0]["rank"], 1)
        self.assertLess(corrected[0]["threshold"], corrected[1]["threshold"])

    def test_an_empty_family_is_empty_not_an_error(self):
        self.assertEqual(family.benjamini_hochberg([]), [])


class TestGatesTogether(unittest.TestCase):

    def test_it_rejects_the_noise_an_uncorrected_threshold_would_promote(self):
        random.seed(7)
        noise = [{"name": f"n{i}", "p": random.random(), "effect": 0.002}
                 for i in range(80)]
        real = [{"name": f"r{i}", "p": 0.0001, "effect": 0.03} for i in range(3)]
        uncorrected = [r for r in noise + real if r["p"] < 0.05]
        result = family.apply_gates(noise + real)
        self.assertEqual({e["name"] for e in result["passed"]},
                         {"r0", "r1", "r2"})
        self.assertGreater(len(uncorrected), len(result["passed"]))

    def test_a_significant_but_trivial_effect_does_not_pass(self):
        # On seven thousand games a tiny effect is easily distinguishable from
        # zero. Significance alone would promote something not worth betting.
        result = family.apply_gates(
            [{"name": "tiny", "p": 0.00001, "effect": 0.001}])
        self.assertTrue(result["all"][0]["survives_fdr"])
        self.assertFalse(result["all"][0]["clears_effect"])
        self.assertEqual(result["passed"], [])

    def test_a_large_effect_that_is_not_significant_does_not_pass(self):
        result = family.apply_gates([{"name": "loud", "p": 0.9, "effect": 0.20}])
        self.assertEqual(result["passed"], [])

    def test_effect_direction_does_not_matter(self):
        result = family.apply_gates(
            [{"name": "neg", "p": 0.0001, "effect": -0.05}])
        self.assertEqual(len(result["passed"]), 1)

    def test_the_whole_family_is_returned_not_just_the_winners(self):
        # Publishing only survivors is how a family of eighty-eight becomes a
        # claim about four.
        result = family.apply_gates(
            [{"name": "a", "p": 0.0001, "effect": 0.05},
             {"name": "b", "p": 0.9, "effect": 0.001}])
        self.assertEqual(len(result["all"]), 2)
        self.assertEqual(len(result["passed"]), 1)

    def test_the_expected_false_count_is_stated_rather_than_hidden(self):
        result = family.apply_gates(
            [{"name": f"r{i}", "p": 0.0001, "effect": 0.05} for i in range(10)])
        self.assertEqual(result["expected_false_among_passed"], 1.0)
        self.assertIn("expected to be noise", result["summary"])


class TestTheRegisteredFamily(unittest.TestCase):
    """The real file, as committed."""

    def test_it_exists_and_is_readable(self):
        payload = family.read()
        self.assertGreater(payload["count"], 0)

    def test_every_hypothesis_names_a_detector_and_a_market(self):
        for hypothesis in family.read()["hypotheses"]:
            self.assertTrue(hypothesis["detector"])
            self.assertTrue(hypothesis["market"])

    def test_the_count_matches_the_list(self):
        payload = family.read()
        self.assertEqual(payload["count"], len(payload["hypotheses"]))

    def test_it_is_bigger_than_the_detector_count(self):
        # The point of the file: eleven detectors are not eleven tests.
        payload = family.read()
        names = {h["detector"] for h in payload["hypotheses"]}
        self.assertGreater(payload["count"], len(names))


if __name__ == "__main__":
    unittest.main()
