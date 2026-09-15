"""Tests for live odds budget band (task 0.4).

Verifies that the LIVE_ODDS band is distinct from LIVE_CAPTURE, that the
kill switch works, that the 300-credit daily cap is enforced, and that new
families ("scores", "tennis_h2h") are correctly configured as unmeasured.
"""

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.capture import budget
from src.pipeline import creditlog

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _write_families(folder, families):
    """Write a tempfile capture_families.json with the given families dict."""
    path = Path(folder) / "capture_families.json"
    path.write_text(json.dumps({"families": families}), encoding="utf-8")
    return path


class LiveOddsBandTests(unittest.TestCase):
    def test_live_odds_in_valid_bands(self):
        """LIVE_ODDS is a recognized band."""
        self.assertIn(budget.LIVE_ODDS, budget.VALID_BANDS)

    def test_live_odds_enabled_with_empty_env(self):
        """live_odds_enabled({}) returns False (feature OFF by default)."""
        self.assertFalse(budget.live_odds_enabled({}))

    def test_live_odds_enabled_with_1(self):
        """live_odds_enabled({"LIVE_ODDS": "1"}) returns True."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "1"}))

    def test_live_odds_enabled_with_true(self):
        """live_odds_enabled({"LIVE_ODDS": "true"}) returns True."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "true"}))

    def test_live_odds_enabled_with_yes(self):
        """live_odds_enabled({"LIVE_ODDS": "yes"}) returns True."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "yes"}))

    def test_live_odds_enabled_with_on(self):
        """live_odds_enabled({"LIVE_ODDS": "on"}) returns True."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "on"}))

    def test_live_odds_enabled_with_0(self):
        """live_odds_enabled({"LIVE_ODDS": "0"}) returns False."""
        self.assertFalse(budget.live_odds_enabled({"LIVE_ODDS": "0"}))

    def test_live_odds_enabled_case_insensitive(self):
        """live_odds_enabled is case-insensitive."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "TRUE"}))
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "Yes"}))
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "ON"}))

    def test_live_odds_enabled_strips_whitespace(self):
        """live_odds_enabled strips leading/trailing whitespace."""
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "  1  "}))
        self.assertTrue(budget.live_odds_enabled({"LIVE_ODDS": "\ttrue\n"}))

    def test_can_spend_live_odds_disabled(self):
        """can_spend_live_odds refuses with "disabled" when feature is off."""
        decision = budget.can_spend_live_odds(100, env={}, remaining=50000)
        self.assertFalse(decision.allowed)
        self.assertIn("disabled", decision.reason)

    def test_can_spend_live_odds_zero_credits_allowed(self):
        """can_spend_live_odds allows zero-credit requests when enabled."""
        decision = budget.can_spend_live_odds(
            0, env={"LIVE_ODDS": "1"}, remaining=50000)
        self.assertTrue(decision.allowed)

    def test_can_spend_live_odds_negative_credits_allowed(self):
        """can_spend_live_odds allows negative-credit requests when enabled."""
        decision = budget.can_spend_live_odds(
            -10, env={"LIVE_ODDS": "1"}, remaining=50000)
        self.assertTrue(decision.allowed)

    def test_can_spend_live_odds_no_quota_readable(self):
        """can_spend_live_odds refuses when remaining is None and unreadable."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            decision = budget.can_spend_live_odds(
                100, env={"LIVE_ODDS": "1"}, now=NOW, store=store)
        self.assertFalse(decision.allowed)
        self.assertIn("quota unreadable", decision.reason)

    def test_can_spend_live_odds_floor_refuse(self):
        """can_spend_live_odds refuses when it would breach the credit floor."""
        # CREDIT_FLOOR is 5000, so remaining - est <= 5000 must refuse.
        # If est=6000 and remaining=5100, then 5100-6000=-900 <= 5000 -> refuse.
        decision = budget.can_spend_live_odds(
            6000, env={"LIVE_ODDS": "1"}, remaining=5100)
        self.assertFalse(decision.allowed)
        self.assertIn("credit floor", decision.reason)

    def test_can_spend_live_odds_cap_refuse(self):
        """can_spend_live_odds refuses when it would exceed LIVE_ODDS_DAILY_CAP."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            # Log 100 credits already spent in the live_odds band today.
            creditlog.log(50000, 0, "test.call", store=store, now=NOW,
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49900, 100, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_ODDS)
            # Try to spend 250 more: 100 + 250 = 350 > 300 (cap).
            decision = budget.can_spend_live_odds(
                250, env={"LIVE_ODDS": "1"}, now=NOW, store=store,
                remaining=50000)
        self.assertFalse(decision.allowed)
        self.assertIn("cap", decision.reason)

    def test_can_spend_live_odds_allowed(self):
        """can_spend_live_odds allows when within cap and floor."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            # Log 100 credits already spent in the live_odds band today.
            creditlog.log(50000, 0, "test.call", store=store, now=NOW,
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49900, 100, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_ODDS)
            # Try to spend 150 more: 100 + 150 = 250 <= 300 (cap).
            decision = budget.can_spend_live_odds(
                150, env={"LIVE_ODDS": "1"}, now=NOW, store=store,
                remaining=50000)
        self.assertTrue(decision.allowed)

    def test_live_odds_rows_dont_count_toward_capture_spent(self):
        """Rows logged with budget_band='live_odds' do not count toward
        capture_spent_today() or spent_today(band=LIVE_CAPTURE)."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            # Log a capture spend.
            creditlog.log(50000, 0, "dense.run", store=store, now=NOW,
                         budget_band=budget.LIVE_CAPTURE)
            creditlog.log(49950, 50, "dense.run", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_CAPTURE)
            # Log a live_odds spend.
            creditlog.log(49950, 0, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=2),
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49850, 100, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=3),
                         budget_band=budget.LIVE_ODDS)
            # capture_spent_today should be 50 (only the LIVE_CAPTURE delta).
            capture_spent = budget.capture_spent_today(now=NOW, store=store)
        self.assertEqual(capture_spent, 50)

    def test_spent_today_with_live_odds_band(self):
        """spent_today(band=LIVE_ODDS) counts only live_odds rows."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            # Log a capture spend.
            creditlog.log(50000, 0, "dense.run", store=store, now=NOW,
                         budget_band=budget.LIVE_CAPTURE)
            creditlog.log(49950, 50, "dense.run", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_CAPTURE)
            # Log a live_odds spend.
            creditlog.log(49950, 0, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=2),
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49850, 100, "test.call", store=store,
                         now=NOW + dt.timedelta(minutes=3),
                         budget_band=budget.LIVE_ODDS)
            # spent_today(band=LIVE_ODDS) should be 100.
            live_odds_spent = budget.spent_today(
                now=NOW, store=store, band=budget.LIVE_ODDS)
        self.assertEqual(live_odds_spent, 100)

    def test_row_band_recognizes_live_odds(self):
        """row_band() recognizes an explicit budget_band='live_odds' field."""
        row = {"budget_band": budget.LIVE_ODDS, "caller": "test"}
        self.assertEqual(budget.row_band(row), budget.LIVE_ODDS)

    def test_delta_band_recognizes_live_odds(self):
        """_delta_band() recognizes an explicit budget_band='live_odds' field."""
        row = {"budget_band": budget.LIVE_ODDS, "caller": "test"}
        band = budget._delta_band(row, 100)
        self.assertEqual(band, budget.LIVE_ODDS)

    def test_status_includes_live_odds_dict(self):
        """status() includes a 'live_odds' key with the required fields."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 0, "test", store=store, now=NOW)
            st = budget.status(now=NOW, store=store)
        self.assertIn("live_odds", st)
        live_odds_status = st["live_odds"]
        self.assertIn("enabled", live_odds_status)
        self.assertIn("spent_today", live_odds_status)
        self.assertIn("cap", live_odds_status)
        self.assertIn("remaining_in_cap", live_odds_status)
        self.assertEqual(live_odds_status["cap"], budget.LIVE_ODDS_DAILY_CAP)

    def test_status_live_odds_enabled_false_by_default(self):
        """status() shows live_odds.enabled=False when env vars are not set."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 0, "test", store=store, now=NOW)
            st = budget.status(now=NOW, store=store)
        self.assertFalse(st["live_odds"]["enabled"])

    def test_status_live_odds_spent_and_remaining(self):
        """status() correctly reports spent and remaining for live_odds."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 0, "test", store=store, now=NOW,
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49800, 200, "test", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_ODDS)
            st = budget.status(now=NOW, store=store)
        self.assertEqual(st["live_odds"]["spent_today"], 200)
        # remaining_in_cap = 300 - 200 = 100
        self.assertEqual(st["live_odds"]["remaining_in_cap"], 100)


class NewFamiliesTests(unittest.TestCase):
    def test_load_families_includes_scores(self):
        """load_families() includes the 'scores' family from config."""
        families = budget.load_families()
        self.assertIn("scores", families)

    def test_load_families_includes_tennis_h2h(self):
        """load_families() includes the 'tennis_h2h' family from config."""
        families = budget.load_families()
        self.assertIn("tennis_h2h", families)

    def test_scores_family_measured_false(self):
        """The 'scores' family has measured=False."""
        families = budget.load_families()
        self.assertFalse(families["scores"]["measured"])

    def test_tennis_h2h_family_measured_false(self):
        """The 'tennis_h2h' family has measured=False."""
        families = budget.load_families()
        self.assertFalse(families["tennis_h2h"]["measured"])

    def test_family_cost_scores_is_none(self):
        """family_cost('scores') returns None (unmeasured)."""
        self.assertIsNone(budget.family_cost("scores"))

    def test_family_cost_tennis_h2h_is_none(self):
        """family_cost('tennis_h2h') returns None (unmeasured)."""
        self.assertIsNone(budget.family_cost("tennis_h2h"))

    def test_can_spend_scores_probe_required(self):
        """can_spend('scores', 1, remaining=50000) refuses as PROBE_REQUIRED."""
        decision = budget.can_spend(
            "scores", 1, remaining=50000, spent=0)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))

    def test_can_spend_tennis_h2h_probe_required(self):
        """can_spend('tennis_h2h', 1, remaining=50000) refuses as PROBE_REQUIRED."""
        decision = budget.can_spend(
            "tennis_h2h", 1, remaining=50000, spent=0)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))


if __name__ == "__main__":
    unittest.main()
