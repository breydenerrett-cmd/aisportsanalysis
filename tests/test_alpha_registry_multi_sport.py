"""Tests for multi-sport hypothesis registration in alpha registry."""

import unittest
from datetime import datetime
from pathlib import Path

from src.research.alpha_registry import read_all


class TestAlphaRegistryMultiSport(unittest.TestCase):
    """Verify the four multi-sport hypotheses are registered correctly."""

    def setUp(self):
        """Load the registry once."""
        self.registry = read_all()
        # Build a map of id -> row for quick lookup
        self.rows_by_id = {row.get("id"): row for row in self.registry}

    def test_four_ids_present_exactly_once(self):
        """All four ids are present exactly once in the registry."""
        expected_ids = {
            "NFL_CARD:market_favourite_model_agreement_v1:h2h",
            "LIVE_V0:mlb_favorite_trails_after_3:h2h",
            "LIVE_V0:mlb_starter_pulled_early:h2h",
            "LIVE_V0:nfl_favorite_trails_halftime:h2h",
        }
        actual_ids = {row.get("id") for row in self.registry
                      if row.get("kind") == "hypothesis" and
                      row.get("id") in expected_ids}
        self.assertEqual(actual_ids, expected_ids)

        # Ensure each id appears exactly once as a registration
        for expected_id in expected_ids:
            count = sum(1 for row in self.registry
                       if row.get("kind") == "hypothesis" and
                       row.get("id") == expected_id)
            self.assertEqual(count, 1,
                           msg=f"id {expected_id} should appear exactly once")

    def test_nfl_card_registration(self):
        """NFL_CARD hypothesis is registered with correct fields."""
        row = self.rows_by_id["NFL_CARD:market_favourite_model_agreement_v1:h2h"]
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "hypothesis")
        self.assertEqual(row["status"], "registered")
        self.assertEqual(row["family"], "NFL_CARD_V1")
        self.assertEqual(row["sport"], "nfl")
        self.assertEqual(row["market"], "h2h")
        self.assertEqual(row["alpha_declared"], 0.05)
        self.assertEqual(row["spec_id"], "market_favourite_model_agreement_v1")
        self.assertEqual(row["source_doc"], "docs/PREREG_MULTI_SPORT_2026-09-14.md")

    def test_mlb_favorite_trails_registration(self):
        """MLB favorite_trails_after_3 is registered with correct fields.

        The registry's own schema REQUIRES `sport` on every registration
        row (REQUIRED_REGISTRATION_FIELDS); the "MLB rows omit sport"
        convention belongs to the odds stores, not to this ledger.
        """
        row = self.rows_by_id["LIVE_V0:mlb_favorite_trails_after_3:h2h"]
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "hypothesis")
        self.assertEqual(row["status"], "registered")
        self.assertEqual(row["family"], "LIVE_V0")
        self.assertEqual(row["sport"], "mlb")
        self.assertEqual(row["market"], "h2h")
        self.assertAlmostEqual(row["alpha_declared"], 0.05 / 3)
        self.assertEqual(row["spec_id"], "mlb_favorite_trails_after_3")
        self.assertEqual(row["source_doc"], "docs/PREREG_MULTI_SPORT_2026-09-14.md")

    def test_mlb_starter_pulled_registration(self):
        """MLB starter_pulled_early is registered with correct fields."""
        row = self.rows_by_id["LIVE_V0:mlb_starter_pulled_early:h2h"]
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "hypothesis")
        self.assertEqual(row["status"], "registered")
        self.assertEqual(row["family"], "LIVE_V0")
        self.assertEqual(row["sport"], "mlb")
        self.assertEqual(row["market"], "h2h")
        self.assertAlmostEqual(row["alpha_declared"], 0.05 / 3)
        self.assertEqual(row["spec_id"], "mlb_starter_pulled_early")
        self.assertEqual(row["source_doc"], "docs/PREREG_MULTI_SPORT_2026-09-14.md")

    def test_nfl_favorite_trails_halftime_registration(self):
        """NFL favorite_trails_halftime is registered with correct fields."""
        row = self.rows_by_id["LIVE_V0:nfl_favorite_trails_halftime:h2h"]
        self.assertIsNotNone(row)
        self.assertEqual(row["kind"], "hypothesis")
        self.assertEqual(row["status"], "registered")
        self.assertEqual(row["family"], "LIVE_V0")
        self.assertEqual(row["sport"], "nfl")
        self.assertEqual(row["market"], "h2h")
        self.assertAlmostEqual(row["alpha_declared"], 0.05 / 3)
        self.assertEqual(row["spec_id"], "nfl_favorite_trails_halftime")
        self.assertEqual(row["source_doc"], "docs/PREREG_MULTI_SPORT_2026-09-14.md")

    def test_all_registered_utc_valid(self):
        """All four hypotheses have valid registered_utc that parses and is 2026-09-14 or 2026-09-15."""
        for hyp_id in [
            "NFL_CARD:market_favourite_model_agreement_v1:h2h",
            "LIVE_V0:mlb_favorite_trails_after_3:h2h",
            "LIVE_V0:mlb_starter_pulled_early:h2h",
            "LIVE_V0:nfl_favorite_trails_halftime:h2h",
        ]:
            row = self.rows_by_id[hyp_id]
            registered_utc_str = row.get("registered_utc")
            self.assertIsNotNone(registered_utc_str,
                               msg=f"{hyp_id} missing registered_utc")
            # Parse as ISO format
            try:
                dt = datetime.fromisoformat(registered_utc_str)
            except (ValueError, TypeError) as e:
                self.fail(f"{hyp_id} registered_utc {registered_utc_str!r} "
                         f"does not parse as ISO format: {e}")
            # Check date is 2026-09-14 or 2026-09-15 UTC
            date_str = registered_utc_str[:10] if isinstance(registered_utc_str, str) else str(dt.date())
            self.assertIn(date_str, ["2026-09-14", "2026-09-15"],
                         msg=f"{hyp_id} registered_utc {registered_utc_str} "
                         f"not dated 2026-09-14 or 2026-09-15")

    def test_source_doc_exists(self):
        """source_doc file exists for all four hypotheses."""
        doc_file = Path(__file__).resolve().parents[1] / "docs" / "PREREG_MULTI_SPORT_2026-09-14.md"
        self.assertTrue(doc_file.exists(),
                       msg=f"source_doc {doc_file} does not exist")

    def test_data_window_correct(self):
        """All four have the correct data_window."""
        expected_window = {
            "discovery": None,
            "replication": "2026-09-15..",
            "sealed_untouched": True
        }
        for hyp_id in [
            "NFL_CARD:market_favourite_model_agreement_v1:h2h",
            "LIVE_V0:mlb_favorite_trails_after_3:h2h",
            "LIVE_V0:mlb_starter_pulled_early:h2h",
            "LIVE_V0:nfl_favorite_trails_halftime:h2h",
        ]:
            row = self.rows_by_id[hyp_id]
            self.assertEqual(row.get("data_window"), expected_window,
                           msg=f"{hyp_id} data_window mismatch")


if __name__ == "__main__":
    unittest.main()
