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


class PerCallBillingTests(unittest.TestCase):
    """R16-L3/D6: live_odds spend is the SUM of each call's own logged
    credits_used_last, never a delta of the remaining balance -- because two
    runners (the forward-capture chain and the live window) interleave
    writes to the credit log, and a delta bills whichever band's row
    happened to land next."""

    def test_a_day_of_percall_captures_sums_to_the_cap_correctly(self):
        """40 one-credit in-play captures, each logging its own
        credits_used_last=1 with budget_band=live_odds, sum to exactly 40 --
        even though ANOTHER writer (the forward-capture chain) appends its
        own balance-checkpoint rows in between, at credits_remaining values
        that would make a delta-based read attribute those drops to the
        wrong band or the wrong size."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            remaining = 50000
            for i in range(40):
                # The chain's own checkpoint: a balance read with no usage
                # of its own (credits_used_last=0), the shape D6 describes
                # 164 of 165 real rows taking (2.2 in the doc).
                creditlog.log(remaining, 0, "dense.run", store=store,
                             now=NOW + dt.timedelta(seconds=i * 90),
                             budget_band=budget.LIVE_CAPTURE)
                # One in-play capture: bills exactly 1 credit of its own.
                remaining -= 1
                creditlog.log(remaining, 1, "live_odds.capture_inplay",
                             store=store,
                             now=NOW + dt.timedelta(seconds=i * 90 + 30),
                             budget_band=budget.LIVE_ODDS)
            live_odds_spent = budget.spent_today(
                now=NOW, store=store, band=budget.LIVE_ODDS)
        self.assertEqual(live_odds_spent, 40)

    def test_interleaved_writer_does_not_inflate_or_hide_live_odds_spend(self):
        """A same-day historical/capture writer logging a LARGE balance
        checkpoint right after an in-play capture must not swallow that
        capture's cost into its own band, and must not zero out live_odds's
        own total either (the exact D6 failure mode: 40 in-play captures
        between two capture-band checkpoints read as live_odds spent 0,
        live_capture spent 43)."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 0, "dense.run", store=store, now=NOW,
                         budget_band=budget.LIVE_CAPTURE)
            for i in range(3):
                creditlog.log(49999 - i, 1, "live_odds.capture_inplay",
                             store=store,
                             now=NOW + dt.timedelta(minutes=i + 1),
                             budget_band=budget.LIVE_ODDS)
            # The chain's next checkpoint lands AFTER all three captures.
            creditlog.log(49990, 0, "dense.run", store=store,
                         now=NOW + dt.timedelta(minutes=10),
                         budget_band=budget.LIVE_CAPTURE)
            live_odds_spent = budget.spent_today(
                now=NOW, store=store, band=budget.LIVE_ODDS)
            capture_spent = budget.capture_spent_today(now=NOW, store=store)
        # live_odds: 3 real captures at 1 credit each.
        self.assertEqual(live_odds_spent, 3)
        # capture: 50000 -> 49990 is a 10-credit drop, of which 3 credits
        # were the in-play captures' own logged cost; only the remaining 7
        # belong to live_capture.
        self.assertEqual(capture_spent, 7)

    def test_can_spend_live_odds_cap_is_the_percall_sum_not_a_delta(self):
        """Interleaving a capture-band checkpoint between two live_odds
        rows must not change what can_spend_live_odds sees as spent today."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 1, "live_odds.capture_inplay", store=store,
                         now=NOW, budget_band=budget.LIVE_ODDS)
            # An interleaved capture-band checkpoint that drops the balance
            # a lot, logged by a different runner in between.
            creditlog.log(49500, 0, "dense.run", store=store,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_CAPTURE)
            creditlog.log(49499, 1, "live_odds.capture_inplay", store=store,
                         now=NOW + dt.timedelta(minutes=2),
                         budget_band=budget.LIVE_ODDS)
            decision = budget.can_spend_live_odds(
                1, env={"LIVE_ODDS": "1"}, now=NOW, store=store,
                remaining=49499)
        # 2 real live_odds credits spent (not 500-ish from a delta reading
        # the interleaved capture-band drop as its own).
        self.assertTrue(decision.allowed)
        self.assertIn("2+1", decision.reason)


class MergedCreditLogTests(unittest.TestCase):
    """R16-L4/D7: budget reads the forward-capture chain's
    data/processed/credit_log.jsonl and the live window's
    data/live/credit_log_live.jsonl merged by timestamp, with neither file
    rewritten or reordered on disk -- an explicit rejection of a git
    union-merge driver, which can reorder lines and break this arithmetic."""

    def test_rows_merges_both_logs_in_time_order_when_no_store_given(self):
        with tempfile.TemporaryDirectory() as folder:
            chain_path = Path(folder) / "chain.jsonl"
            live_path = Path(folder) / "live.jsonl"
            creditlog.log(50000, 0, "dense.run", store=chain_path, now=NOW,
                         budget_band=budget.LIVE_CAPTURE)
            creditlog.log(49999, 1, "live_odds.capture_inplay",
                         store=live_path,
                         now=NOW + dt.timedelta(minutes=1),
                         budget_band=budget.LIVE_ODDS)
            creditlog.log(49950, 49, "dense.run", store=chain_path,
                         now=NOW + dt.timedelta(minutes=2),
                         budget_band=budget.LIVE_CAPTURE)

            original_chain = budget.CREDIT_LOG_PATH
            original_live = budget.LIVE_CREDIT_LOG_PATH
            budget.CREDIT_LOG_PATH = chain_path
            budget.LIVE_CREDIT_LOG_PATH = live_path
            try:
                rows = budget._rows()
            finally:
                budget.CREDIT_LOG_PATH = original_chain
                budget.LIVE_CREDIT_LOG_PATH = original_live

        self.assertEqual(len(rows), 3)
        utcs = [r["utc"] for r in rows]
        self.assertEqual(utcs, sorted(utcs))
        self.assertEqual([r["caller"] for r in rows],
                         ["dense.run", "live_odds.capture_inplay", "dense.run"])

    def test_explicit_store_bypasses_the_merge(self):
        """Every existing test in this module passes an explicit `store` --
        that path is read alone, unmerged, exactly as before R16-L4."""
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50000, 0, "test", store=store, now=NOW)
            rows = budget._rows(store)
        self.assertEqual(len(rows), 1)


class NewFamiliesTests(unittest.TestCase):
    """The two families added for scores and tennis exist in the real config
    (a config fact), and an UNMEASURED entry for either is refused as
    PROBE_REQUIRED (a behaviour fact, checked against an injected config).

    The behaviour tests used to read the real config/capture_families.json
    and assert that both families were still unmeasured. The daily loop's
    probe step measures a family the first time it runs, so those tests went
    red the morning the `scores` probe landed (2026-09-15) without any code
    changing. A test that reads the disk passes or fails by machine and by
    date; the seam (`path` / `families_path`) is injected instead.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = _write_families(self.tmp.name, {
            "scores": {"measured": False,
                       "reason": "not yet probed in this test"},
            "tennis_h2h": {"measured": False,
                           "reason": "not yet probed in this test"},
        })

    def test_load_families_includes_scores(self):
        """The real config declares the 'scores' family."""
        families = budget.load_families()
        self.assertIn("scores", families)

    def test_load_families_includes_tennis_h2h(self):
        """The real config declares the 'tennis_h2h' family."""
        families = budget.load_families()
        self.assertIn("tennis_h2h", families)

    def test_real_config_entries_carry_a_measured_flag(self):
        """Whatever the probe has done by now, both real entries say so
        explicitly: `measured` is a bool, and a measured entry names its
        measurement time and cost."""
        families = budget.load_families()
        for name in ("scores", "tennis_h2h"):
            entry = families[name]
            self.assertIsInstance(entry.get("measured"), bool, name)
            if entry["measured"]:
                self.assertTrue(entry.get("measured_utc"), name)
                self.assertIsNotNone(entry.get("credits_per_event"), name)

    def test_scores_family_measured_false(self):
        """An unmeasured 'scores' entry loads as measured=False."""
        families = budget.load_families(self.path)
        self.assertFalse(families["scores"]["measured"])

    def test_tennis_h2h_family_measured_false(self):
        """An unmeasured 'tennis_h2h' entry loads as measured=False."""
        families = budget.load_families(self.path)
        self.assertFalse(families["tennis_h2h"]["measured"])

    def test_family_cost_scores_is_none(self):
        """family_cost('scores') is None while the family is unmeasured."""
        self.assertIsNone(budget.family_cost("scores", path=self.path))

    def test_family_cost_tennis_h2h_is_none(self):
        """family_cost('tennis_h2h') is None while the family is unmeasured."""
        self.assertIsNone(budget.family_cost("tennis_h2h", path=self.path))

    def test_can_spend_scores_probe_required(self):
        """can_spend on an unmeasured 'scores' refuses as PROBE_REQUIRED."""
        decision = budget.can_spend(
            "scores", 1, remaining=50000, spent=0, families_path=self.path)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))

    def test_can_spend_tennis_h2h_probe_required(self):
        """can_spend on an unmeasured 'tennis_h2h' refuses as PROBE_REQUIRED."""
        decision = budget.can_spend(
            "tennis_h2h", 1, remaining=50000, spent=0,
            families_path=self.path)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))


if __name__ == "__main__":
    unittest.main()
