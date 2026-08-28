"""Tests for src/model/pointintime.py.

A season-to-date statistic applied to an earlier game in that season is the most
effective backtest-inflating bug there is, and it is invisible: the numbers are
real, the code is correct, and the result is a lie. Conventions do not survive a
long autonomous run, so the audit is data and the guard raises.
"""

import unittest

from src.detect import base, detectors
from src.model import pointintime as pit


class TestInputAudit(unittest.TestCase):

    def test_forward_accumulated_inputs_are_clean(self):
        for name in ("team_features", "starters", "bullpen", "travel", "market"):
            self.assertEqual(pit.input_status(name)["status"], pit.CLEAN, name)

    def test_season_to_date_inputs_are_leaky(self):
        for name in ("splits", "arsenals", "matchup_history"):
            self.assertEqual(pit.input_status(name)["status"], pit.LEAKY, name)

    def test_every_leaky_input_says_why_and_what_would_unblock_it(self):
        # A blocker with no route out becomes permanent by default.
        for name, entry in pit.INPUTS.items():
            if entry["status"] == pit.LEAKY:
                self.assertTrue(entry["why"], name)
                self.assertTrue(entry.get("unblocked_by"), name)

    def test_an_unaudited_input_is_unknown_not_assumed_clean(self):
        # The dangerous default. A new input must be audited before it can be
        # used historically, and silence must not read as approval.
        self.assertEqual(pit.input_status("something_new")["status"], pit.UNKNOWN)

    def test_the_splits_finding_is_recorded_with_its_evidence(self):
        # Requesting three different date ranges for one pitcher returned
        # byte-identical numbers. That measurement is why this is LEAKY and not
        # merely "be careful", so it lives in the reason.
        why = pit.input_status("splits")["why"]
        self.assertIn("IGNORES startDate and endDate", why)
        self.assertIn("byte-identical", why)


class TestDetectorInherits(unittest.TestCase):

    def setUp(self):
        # A synthetic detector mixing a clean and a leaky input. The real four
        # were remapped to the rebuilt inputs and are clean now, but the
        # inheritance rule they used to demonstrate still needs proving.
        pit.DETECTOR_INPUTS["_mixed"] = ("lineups", "splits")
        self.addCleanup(pit.DETECTOR_INPUTS.pop, "_mixed", None)

    def test_a_detector_is_only_as_clean_as_its_dirtiest_input(self):
        entry = pit.detector_status("_mixed")
        self.assertEqual(entry["status"], pit.LEAKY)
        self.assertIn("lineups", entry["inputs"])

    def test_a_detector_with_only_clean_inputs_is_clean(self):
        self.assertEqual(pit.detector_status("starter_mismatch")["status"],
                         pit.CLEAN)

    def test_an_undeclared_detector_is_unknown(self):
        self.assertEqual(pit.detector_status("brand_new")["status"], pit.UNKNOWN)

    def test_the_route_out_is_carried_up_to_the_detector(self):
        entry = pit.detector_status("_mixed")
        self.assertTrue(entry["unblocked_by"])
        self.assertIn("Statcast", " ".join(entry["unblocked_by"]))

    def test_the_rebuilt_sections_made_the_four_detectors_evaluable(self):
        # The whole point of the rebuilt store: these four were the excluded
        # ones, and each now reads only forward-accumulated inputs.
        for name in ("platoon_mismatch", "pitch_mix_mismatch",
                     "thin_matchup_history", "lineup_vs_starter"):
            self.assertEqual(pit.detector_status(name)["status"],
                             pit.CLEAN, name)

    def test_the_rebuilt_inputs_are_audited_clean(self):
        for name in ("rebuilt_splits", "rebuilt_arsenals", "rebuilt_matchup"):
            self.assertEqual(pit.input_status(name)["status"], pit.CLEAN, name)


class TestGuard(unittest.TestCase):
    """The four once-leaky detectors are now CLEAN (remapped to rebuilt_*
    inputs), so the guard is exercised through a probe detector wired to the
    still-leaky LIVE-fetch inputs -- which remain in INPUTS precisely so that
    anything reading those endpoints stays refused."""

    def setUp(self):
        pit.DETECTOR_INPUTS["_live_splits_probe"] = ("lineups", "splits")
        pit.DETECTOR_INPUTS["_live_arsenal_probe"] = ("arsenals",)

    def tearDown(self):
        pit.DETECTOR_INPUTS.pop("_live_splits_probe", None)
        pit.DETECTOR_INPUTS.pop("_live_arsenal_probe", None)

    def test_a_leaky_detector_raises_rather_than_warning(self):
        # A warning in a batch job is a line nobody reads, and the number it
        # accompanies is the one that gets quoted.
        with self.assertRaises(pit.PointInTimeError) as ctx:
            pit.require_clean("_live_splits_probe")
        self.assertIn("cannot be evaluated historically", str(ctx.exception))

    def test_the_error_names_what_would_unblock_it(self):
        with self.assertRaises(pit.PointInTimeError) as ctx:
            pit.require_clean("_live_arsenal_probe")
        self.assertIn("unblocked by", str(ctx.exception))

    def test_an_unaudited_detector_also_raises(self):
        with self.assertRaises(pit.PointInTimeError):
            pit.require_clean("brand_new")

    def test_a_clean_detector_passes(self):
        self.assertEqual(pit.require_clean("travel_load")["status"], pit.CLEAN)


class TestTheRealFamily(unittest.TestCase):

    def setUp(self):
        self._saved = base.registry()
        base.clear_registry()
        detectors.register_defaults()

    def tearDown(self):
        base.clear_registry()
        for detector in self._saved.values():
            base.register(detector)

    def test_every_registered_detector_has_declared_its_inputs(self):
        # An undeclared detector would silently be excluded from discovery as
        # "unknown", which looks the same as being unevaluable for a real reason.
        for name in base.registry():
            self.assertIn(name, pit.DETECTOR_INPUTS, name)

    def test_the_audit_splits_the_family_and_loses_nobody(self):
        result = pit.audit(base.registry())
        total = len(result["clean"]) + len(result["leaky"]) + len(result["unknown"])
        self.assertEqual(total, len(base.registry()))

    def test_some_detectors_survive_the_audit(self):
        # If nothing were evaluable there would be no discovery pass to run.
        self.assertGreater(len(pit.audit(base.registry())["clean"]), 0)


if __name__ == "__main__":
    unittest.main()
