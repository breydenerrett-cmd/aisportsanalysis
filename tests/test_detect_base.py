"""Tests for src/detect/base.py.

The two constructor guards are the point of this file. Both encode a rule that
was learned the hard way and would otherwise decay into a comment nobody reads:
a signal without a baseline is a description, and a blocked detector without a
reason is indistinguishable from a broken one.
"""

import unittest

from src.detect import base


class TestBaselineIsMandatory(unittest.TestCase):
    """The product is "true and not already in your head". That needs a baseline."""

    def test_a_signal_without_a_baseline_raises(self):
        with self.assertRaises(base.DetectorError) as ctx:
            base.Finding("d", base.SIGNAL, "their starter has a 3.80 ERA")
        self.assertIn("description", str(ctx.exception))

    def test_a_signal_with_a_baseline_is_fine(self):
        finding = base.Finding("d", base.SIGNAL, "x", value=4.9, baseline=4.2)
        self.assertEqual(finding.kind, base.SIGNAL)

    def test_context_and_debunk_need_no_baseline(self):
        # A debunk's whole content is "this number means nothing", which has no
        # baseline by construction.
        for kind in (base.CONTEXT, base.DEBUNK):
            self.assertEqual(base.Finding("d", kind, "x").kind, kind)

    def test_a_zero_baseline_still_counts_as_present(self):
        # 0.0 is falsy. A truthiness check here would reject the implied-bullpen
        # detector, whose baseline is exactly zero.
        finding = base.Finding("d", base.SIGNAL, "x", value=0.04, baseline=0.0)
        self.assertEqual(finding.baseline, 0.0)


class TestSurpriseScore(unittest.TestCase):
    """A huge number from a tiny denominator is how noise reaches the top."""

    def test_scored_in_units_of_spread(self):
        self.assertEqual(base.surprise_score(5.0, 4.0, 0.5), 2.0)

    def test_direction_does_not_matter(self):
        self.assertEqual(base.surprise_score(3.0, 4.0, 0.5),
                         base.surprise_score(5.0, 4.0, 0.5))

    def test_zero_spread_returns_none_rather_than_dividing(self):
        self.assertIsNone(base.surprise_score(5.0, 4.0, 0))

    def test_missing_inputs_return_none(self):
        self.assertIsNone(base.surprise_score(None, 4.0, 0.5))
        self.assertIsNone(base.surprise_score(5.0, None, 0.5))


class TestDeclarations(unittest.TestCase):

    def test_a_detector_must_be_named(self):
        with self.assertRaises(base.DetectorError):
            type("Anon", (base.Detector,), {})

    def test_a_blocked_detector_must_give_a_reason(self):
        with self.assertRaises(base.DetectorError) as ctx:
            type("Mute", (base.Detector,),
                 {"name": "mute", "status": base.BLOCKED})
        self.assertIn("broken", str(ctx.exception))

    def test_a_blocked_detector_with_a_reason_declares_fine(self):
        cls = type("Fine", (base.Detector,),
                   {"name": "fine", "status": base.BLOCKED,
                    "blocked_reason": "the data does not exist"})
        self.assertEqual(cls.status, base.BLOCKED)

    def test_unknown_kinds_and_statuses_are_rejected(self):
        with self.assertRaises(base.DetectorError):
            base.Finding("d", "interesting", "x")
        with self.assertRaises(base.DetectorError):
            base.Finding("d", base.CONTEXT, "x", evidence="probably_true")
        with self.assertRaises(base.DetectorError):
            base.Finding("d", base.CONTEXT, "x", side="left")


class TestSafeRun(unittest.TestCase):
    """A detector that vanishes looks identical to one that had nothing to say."""

    def test_a_raising_detector_becomes_a_visible_blocked_finding(self):
        boom = type("Boom", (base.Detector,),
                    {"name": "boom",
                     "run": lambda self, g: (_ for _ in ()).throw(ValueError("no"))})()
        findings = boom.safe_run({})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence, base.BLOCKED)
        self.assertIn("boom failed", findings[0].claim)

    def test_a_blocked_detector_says_why_without_running(self):
        cls = type("Mute", (base.Detector,),
                   {"name": "mute", "status": base.BLOCKED,
                    "blocked_reason": "no lineups yet",
                    "run": lambda self, g: (_ for _ in ()).throw(AssertionError)})
        findings = cls().safe_run({})
        self.assertIn("no lineups yet", findings[0].claim)

    def test_silence_is_normal(self):
        quiet = type("Quiet", (base.Detector,),
                     {"name": "quiet", "run": lambda self, g: []})()
        self.assertEqual(quiet.safe_run({}), [])


class TestRanking(unittest.TestCase):

    def make(self, kind, surprise):
        return base.Finding("d", kind, "x", value=1, baseline=0, surprise=surprise)

    def test_signals_outrank_debunks_which_outrank_context(self):
        found = base.rank([self.make(base.CONTEXT, 9.0),
                           self.make(base.DEBUNK, 8.0),
                           self.make(base.SIGNAL, 0.1)])
        self.assertEqual([f.kind for f in found],
                         [base.SIGNAL, base.DEBUNK, base.CONTEXT])

    def test_context_never_outranks_a_signal_however_large(self):
        # Context is by definition what the reader already assumes. A large
        # number attached to it is still not news.
        found = base.rank([self.make(base.CONTEXT, 99.0),
                           self.make(base.SIGNAL, 0.01)])
        self.assertEqual(found[0].kind, base.SIGNAL)

    def test_more_surprising_signals_come_first(self):
        found = base.rank([self.make(base.SIGNAL, 1.0), self.make(base.SIGNAL, 3.0)])
        self.assertEqual([f.surprise for f in found], [3.0, 1.0])

    def test_unscored_findings_sort_after_scored_ones(self):
        found = base.rank([self.make(base.SIGNAL, None), self.make(base.SIGNAL, 0.2)])
        self.assertEqual(found[0].surprise, 0.2)
        self.assertTrue(found[1].unscored)


class TestRegistry(unittest.TestCase):
    """The registry is the pre-registered hypothesis count, not a convenience."""

    def setUp(self):
        self._saved = base.registry()
        base.clear_registry()

    def tearDown(self):
        base.clear_registry()
        for detector in self._saved.values():
            base.register(detector)

    def test_duplicate_names_are_refused(self):
        cls = type("Dup", (base.Detector,), {"name": "dup", "run": lambda s, g: []})
        base.register(cls())
        with self.assertRaises(base.DetectorError):
            base.register(cls())

    def test_run_all_uses_the_registry_by_default(self):
        cls = type("One", (base.Detector,),
                   {"name": "one",
                    "run": lambda s, g: [base.Finding("one", base.CONTEXT, "hi")]})
        base.register(cls())
        self.assertEqual([f.claim for f in base.run_all({})], ["hi"])

    def test_run_all_accepts_an_explicit_list(self):
        cls = type("Two", (base.Detector,),
                   {"name": "two",
                    "run": lambda s, g: [base.Finding("two", base.CONTEXT, "yo")]})
        self.assertEqual([f.claim for f in base.run_all({}, [cls()])], ["yo"])


if __name__ == "__main__":
    unittest.main()
