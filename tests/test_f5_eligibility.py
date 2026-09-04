"""Tests for the F5 eligibility boundary (src/research/f5_eligibility.py).

This module never touches data/historical/odds_first_five or any live
provider -- every case here is a bare `date` string or an in-memory dict.
The cross-module regression proving a 2025 row can exist in F5_RAW_HISTORY
while being excluded from F5_TMINUS2_PRIMARY lives in
tests/test_f5_tminus2.py (it needs the raw-history file I/O this module
does not have).
"""

import unittest

from src.research import f5_eligibility as elig


class TestEligibility(unittest.TestCase):

    def test_in_window_2023_date_is_eligible(self):
        v = elig.eligibility("2023-06-01")
        self.assertTrue(v["eligible"])
        self.assertFalse(v["TUNING_ONLY"])
        self.assertIsNone(v["reason"])

    def test_in_window_2024_date_is_eligible(self):
        self.assertTrue(elig.is_eligible("2024-09-01"))

    def test_window_start_is_inclusive(self):
        self.assertTrue(elig.is_eligible(elig.APPROVED_WINDOW_START))

    def test_window_end_is_inclusive(self):
        self.assertTrue(elig.is_eligible(elig.APPROVED_WINDOW_END))

    def test_one_day_before_window_start_is_ineligible(self):
        v = elig.eligibility("2023-05-09")
        self.assertFalse(v["eligible"])
        self.assertEqual(v["reason"], "outside_approved_window")
        self.assertFalse(v["TUNING_ONLY"])

    def test_one_day_after_window_end_is_ineligible(self):
        v = elig.eligibility("2024-10-08")
        self.assertFalse(v["eligible"])
        self.assertEqual(v["reason"], "outside_approved_window")

    def test_the_real_pre_window_sanity_tranche_dates(self):
        for date in ("2023-03-30", "2023-05-06"):
            with self.subTest(date=date):
                v = elig.eligibility(date)
                self.assertFalse(v["eligible"])
                self.assertEqual(v["reason"], "outside_approved_window")
                self.assertFalse(v["TUNING_ONLY"])

    def test_every_2025_date_is_tuning_only_and_ineligible(self):
        for date in ("2025-01-01", "2025-04-28", "2025-05-09", "2025-05-16",
                    "2025-08-13", "2025-08-19", "2025-09-22", "2025-12-31"):
            with self.subTest(date=date):
                v = elig.eligibility(date)
                self.assertFalse(v["eligible"])
                self.assertTrue(v["TUNING_ONLY"])
                self.assertEqual(v["reason"], "tuning_only_2025")

    def test_2025_is_tuning_only_even_if_hypothetically_in_window_bounds(self):
        # The 2025 rule is about the calendar year, not just today's window
        # endpoints -- a 2025 date that would otherwise fall inside a
        # window shape identical to 2023-05-10..2024-10-07 must still be
        # excluded, because "2025 is tuning-only forever" is a standing
        # project rule independent of any one window's bounds.
        v = elig.eligibility("2025-06-15")
        self.assertFalse(v["eligible"])
        self.assertTrue(v["TUNING_ONLY"])

    def test_2026_is_sealed_and_ineligible_but_not_flagged_tuning_only(self):
        v = elig.eligibility("2026-05-01")
        self.assertFalse(v["eligible"])
        self.assertFalse(v["TUNING_ONLY"])
        self.assertEqual(v["reason"], "sealed_2026")

    def test_missing_date_is_ineligible_not_silently_admitted(self):
        for missing in (None, "", 0):
            with self.subTest(missing=missing):
                v = elig.eligibility(missing)
                self.assertFalse(v["eligible"])
                self.assertEqual(v["reason"], "date_missing")

    def test_reason_is_none_only_when_eligible(self):
        for date in ("2022-01-01", "2023-05-10", "2024-10-07", "2025-01-01",
                    "2026-01-01", None):
            v = elig.eligibility(date)
            self.assertEqual(v["reason"] is None, v["eligible"])


class TestAnnotate(unittest.TestCase):

    def test_annotate_is_additive_and_does_not_mutate_the_input(self):
        row = {"game_pk": "1", "date": "2025-08-13", "status": "OK"}
        out = elig.annotate(row)

        self.assertIsNot(out, row)
        self.assertEqual(row, {"game_pk": "1", "date": "2025-08-13", "status": "OK"})

        self.assertEqual(out["game_pk"], "1")
        self.assertEqual(out["status"], "OK")
        self.assertTrue(out["TUNING_ONLY"])
        self.assertFalse(out["eligible_for_research"])
        self.assertEqual(out["ineligibility_reason"], "tuning_only_2025")

    def test_annotate_on_an_eligible_row_flags_it_as_such(self):
        row = {"game_pk": "2", "date": "2024-06-01"}
        out = elig.annotate(row)
        self.assertFalse(out["TUNING_ONLY"])
        self.assertTrue(out["eligible_for_research"])
        self.assertIsNone(out["ineligibility_reason"])


if __name__ == "__main__":
    unittest.main()
