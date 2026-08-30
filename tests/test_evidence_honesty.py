"""The claims the product makes about its own reliability.

These lock the one thing this system must never get wrong: a reader must not be
able to mistake a refuted claim for an open question, or an open question for a
result. Every assertion here corresponds to a finding in docs/RESULTS_STAGE2.md
or docs/RESULTS_V2.md, so if a detector is ever promoted, the evidence has to
exist before these tests will pass.
"""

import unittest

from pathlib import Path

from src.detect import base as detect
from src.detect import detectors as detectors_mod
from src.report import dashboard


def _source() -> str:
    return Path(detectors_mod.__file__).read_text(encoding="utf-8")


# Evaluated in the Stage 2 clean rerun. Every one failed the FDR and
# effect-size gates -- see docs/RESULTS_STAGE2.md.
TESTED_AND_NULL = {
    "bullpen_workload", "stale_book", "starter_mismatch", "platoon_mismatch",
    "lineup_vs_starter", "travel_load", "bullpen_exposure", "pitch_mix_mismatch",
}


class TaxonomyTests(unittest.TestCase):
    def test_tested_null_is_weaker_than_unproven(self):
        """An untested guess might work. A refuted one does not."""
        order = detect.EVIDENCE_ORDER
        self.assertLess(order.index(detect.TESTED_NULL),
                        order.index(detect.UNPROVEN))

    def test_every_evidence_state_has_a_label_a_reader_can_understand(self):
        for state in detect.EVIDENCE_ORDER:
            self.assertIn(state, dashboard.EVIDENCE_LABELS,
                          f"{state} would render without an explanation")
            label, meaning = dashboard.EVIDENCE_LABELS[state]
            self.assertTrue(label and meaning)

    def test_nothing_in_the_system_claims_to_be_proven(self):
        """Two families, thirteen hypotheses, zero survivors.

        This test fails the moment a detector is labelled PROVEN. That is the
        point: promoting one has to be a deliberate act that updates this file
        alongside the evidence, not something that slips through.
        """
        source = _source()
        self.assertNotIn("evidence=PROVEN", source)
        self.assertNotIn("evidence=PROVISIONAL", source)


class DetectorLabelTests(unittest.TestCase):
    def test_every_stage_two_detector_is_labelled_tested_null(self):
        source = _source()
        blocks = _class_blocks(source)
        for name in TESTED_AND_NULL:
            body = blocks.get(name)
            self.assertIsNotNone(body, f"detector {name} not found")
            self.assertNotIn("evidence=UNPROVEN", body,
                             f"{name} was tested and failed; 'never tested' is wrong")
            self.assertNotIn("evidence=HISTORICAL_CANDIDATE", body,
                             f"{name} was tested and failed; it is not a candidate")

    def test_an_untested_detector_is_still_allowed_to_say_so(self):
        """implied_bullpen_disagreement was never in the Stage 2 family."""
        blocks = _class_blocks(_source())
        self.assertIn("evidence=UNPROVEN", blocks["implied_bullpen_disagreement"])


class RankingTests(unittest.TestCase):
    def _finding(self, evidence, surprise, kind=detect.SIGNAL):
        return detect.Finding("d", kind, "claim", value=1, baseline=0,
                              sample="n", surprise=surprise, evidence=evidence)

    def test_a_refuted_claim_never_outranks_an_open_one_on_size_alone(self):
        refuted = self._finding(detect.TESTED_NULL, surprise=9.0)
        open_question = self._finding(detect.UNPROVEN, surprise=0.1)
        ranked = detect.rank([refuted, open_question])
        self.assertIs(ranked[0], open_question)

    def test_surprise_still_orders_claims_of_equal_evidence(self):
        small = self._finding(detect.UNPROVEN, surprise=0.5)
        large = self._finding(detect.UNPROVEN, surprise=4.0)
        self.assertIs(detect.rank([small, large])[0], large)

    def test_context_never_outranks_a_signal(self):
        context = self._finding(detect.PROVEN, 9.0, kind=detect.CONTEXT)
        signal = self._finding(detect.TESTED_NULL, 0.1, kind=detect.SIGNAL)
        self.assertIs(detect.rank([context, signal])[0], signal)


def _class_blocks(source) -> dict:
    """Detector source split by the `name = "..."` marker each class carries."""
    import re
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r'\n    name = "([a-z_]+)"', source)]
    blocks = {}
    for index, (position, name) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(source)
        blocks[name] = source[position:end]
    return blocks


if __name__ == "__main__":
    unittest.main()
