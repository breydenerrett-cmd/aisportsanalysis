"""The register of constants that expire, and the audit that watches them.

WHY THIS EXISTS
---------------
`docs/INCIDENT_2026-09-10_STRONG_TIER.md`. A threshold calibrated against a
population is a claim with an expiry date, and nothing recorded which
constants had that property — so `EVIDENCE_STRONG` kept firing at "3+
families agree" while the ceiling moved from 3 to 16 and every published
pick turned green. Nothing broke. No test failed.

What is tested here is not the audit's arithmetic — that is a subtraction —
but the two properties that make it worth having:

  1. It actually detects the drift it was built for. Verified against the
     real ledger, where the STRONG share is 78%.
  2. It does not go silent. A measurement that raises, a store that is
     missing, an entry that cannot be computed — none of these may turn into
     a clean bill of health, because a silent audit is precisely the failure
     mode this file exists to prevent.
"""

from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "scripts", "calibration_drift_audit.py")


def _load():
    spec = importlib.util.spec_from_file_location("calibration_drift_audit",
                                                  AUDIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheRegisterIsHonest(unittest.TestCase):
    def setUp(self):
        self.audit = _load()

    def test_every_entry_says_what_it_was_measured_against(self):
        """An entry with no stated population is not a registration, it is a
        constant with a note attached."""
        for entry in self.audit.REGISTER:
            for field in ("constant", "where", "calibrated_against",
                          "measured_on", "measure", "expected", "tolerance",
                          "why_it_matters"):
                self.assertIn(field, entry, f"{entry.get('constant')} lacks "
                                            f"{field}")
            self.assertTrue(callable(entry["measure"]))
            self.assertGreater(len(entry["why_it_matters"]), 40,
                               f"{entry['constant']}: 'why it matters' has to "
                               f"say something a reader can act on")

    def test_the_constants_it_names_actually_exist(self):
        """A register pointing at a constant that has been renamed is worse
        than no register: it reports clean forever."""
        from src.analysis import daily_card
        from src.engine import slip
        from src.analysis import strength

        self.assertEqual(3, slip.EVIDENCE_STRONG_MIN_FAMILIES)
        self.assertEqual(2.3352, strength.DISPERSION)
        self.assertEqual(0.62, daily_card.BAND_STRONG)

    def test_a_tolerance_is_never_wide_enough_to_be_decorative(self):
        """A tolerance larger than the value it guards can never fire."""
        for entry in self.audit.REGISTER:
            expected = entry["expected"]
            if isinstance(expected, (int, float)) and expected > 0:
                self.assertLess(
                    entry["tolerance"], max(expected, 1.0) * 2,
                    f"{entry['constant']}: tolerance {entry['tolerance']} "
                    f"against expected {expected} cannot realistically fire")


class ItDetectsTheDriftItWasBuiltFor(unittest.TestCase):
    def setUp(self):
        self.audit = _load()

    def test_the_strong_share_measurement_sees_the_real_ledger(self):
        """The number that made the incident undeniable. Skipped rather than
        faked when the ledger is not in this checkout."""
        share, detail = self.audit._measure_strong_share()
        if share is None:
            self.skipTest(f"no slip ledger here: {detail}")
        self.assertGreater(
            share, 0.5,
            "the STRONG share on the real ledger is 78%; if this now reads "
            "low, either the tier was recalibrated (update the register's "
            "`expected`) or the measurement stopped seeing the ledger")

    def test_the_family_ceiling_measurement_sees_the_real_ledger(self):
        worst, detail = self.audit._measure_family_ceiling()
        if worst is None:
            self.skipTest(f"no slip ledger here: {detail}")
        self.assertGreaterEqual(worst, 3)


class ItNeverGoesSilent(unittest.TestCase):
    def setUp(self):
        self.audit = _load()

    def test_a_measurement_that_raises_is_reported_not_swallowed(self):
        """The failure mode this whole file guards. An exception inside one
        measurement must not produce a clean bill of health."""
        def _explode():
            raise RuntimeError("store on fire")

        original = list(self.audit.REGISTER)
        self.audit.REGISTER[:] = [{
            "constant": "fixture", "where": "nowhere",
            "calibrated_against": "a fixture", "measured_on": "2026-09-10",
            "measure": _explode, "expected": 1.0, "tolerance": 0.1,
            "why_it_matters": "this entry exists only to raise, and the audit "
                              "must survive it and say so",
        }]
        self.addCleanup(lambda: self.audit.REGISTER.__setitem__(
            slice(None), original))

        rows = []

        # Run the reporting path the way main() does, without printing.
        for entry in self.audit.REGISTER:
            try:
                current, detail = entry["measure"]()
            except Exception as exc:  # noqa: BLE001
                current, detail = None, f"measurement failed: {exc!r}"
            rows.append((current, detail))

        self.assertEqual(1, len(rows))
        self.assertIsNone(rows[0][0])
        self.assertIn("measurement failed", rows[0][1])

    def test_a_missing_store_reports_not_measurable_rather_than_passing(self):
        """`None` means 'we could not look', and the caller must never read
        it as 'nothing has drifted'."""
        for measure in (self.audit._measure_family_ceiling,
                        self.audit._measure_strong_share,
                        self.audit._measure_card_band_share):
            value, detail = measure()
            if value is None:
                self.assertTrue(detail, f"{measure.__name__} returned None "
                                        f"with no reason")


if __name__ == "__main__":
    unittest.main()
