"""Pin EVIDENCE_LABELS to a single, shared definition.

BACKGROUND
----------
The 2026-08-31 architecture audit found EVIDENCE_LABELS defined twice --
once in src/analysis/synthesis.py (the domain layer) and once, independently,
in src/report/dashboard.py -- and the two had already drifted: dashboard's
copy was missing the OBSERVED entry synthesis carries. Nothing noticed
because nothing compared them.

That drift is dangerous specifically because this product's credibility
rests on evidence labels meaning one thing everywhere they appear. Two
copies is not a style nit, it is a live risk that a page can someday show a
label that overstates confidence relative to what the domain layer actually
believes.

dashboard.py now imports the dict directly (`EVIDENCE_LABELS =
synthesis_mod.EVIDENCE_LABELS`) rather than retyping it, so this test is
mostly a tripwire against someone re-introducing a second, independent copy
later -- e.g. by pasting the dict back in during a refactor.
"""
import unittest

from src.analysis import synthesis
from src.report import dashboard
from src.detect import base as detect


class EvidenceLabelsUnifiedTests(unittest.TestCase):
    def test_dashboard_and_synthesis_share_the_same_object(self):
        # `is`, not `==` -- this is the actual guarantee: one dict, one
        # source of truth, not two dicts that happen to compare equal today
        # and can silently diverge tomorrow the way they already did once.
        self.assertIs(
            dashboard.EVIDENCE_LABELS, synthesis.EVIDENCE_LABELS,
            "dashboard.EVIDENCE_LABELS and synthesis.EVIDENCE_LABELS must be "
            "the same object -- a second, independent definition is exactly "
            "the bug this test exists to catch.",
        )

    def test_every_detector_evidence_state_has_a_label(self):
        # Every state the detector ladder can hand back must resolve to a
        # label. A missing entry is how a claim ends up on the page with no
        # evidence stamp at all.
        states = [
            detect.PROVEN, detect.FORWARD_TESTING, detect.PROVISIONAL,
            detect.TUNING_EVIDENCE, detect.HISTORICAL_CANDIDATE,
            detect.UNPROVEN, detect.TESTED_NULL, detect.BLOCKED,
        ]
        for state in states:
            self.assertIn(state, synthesis.EVIDENCE_LABELS)
            self.assertIn(state, dashboard.EVIDENCE_LABELS)

    def test_observed_is_a_real_label_not_a_prediction_word(self):
        # OBSERVED is the one non-detector status (a quoted price, not a
        # hypothesis) and it must say so -- it must not read like EV or an
        # edge, per the project's evidence rules.
        label, meaning = synthesis.EVIDENCE_LABELS[synthesis.OBSERVED]
        self.assertEqual(label, "Observed")
        self.assertIn("not expected value", meaning)
        self.assertIn("not a prediction", meaning)

    def test_tested_null_is_strictly_weaker_than_unproven(self):
        # The documented ordering property the audit flagged: a hypothesis
        # that was actually tested and failed must never outrank one that
        # was simply never tested. If this flips, a refuted idea could
        # outscore an untested guess -- exactly backwards for a product
        # whose whole point is not letting a refuted idea read as open.
        self.assertLess(
            synthesis.EVIDENCE_FACTOR[detect.TESTED_NULL],
            synthesis.EVIDENCE_FACTOR[detect.UNPROVEN],
        )


if __name__ == "__main__":
    unittest.main()
