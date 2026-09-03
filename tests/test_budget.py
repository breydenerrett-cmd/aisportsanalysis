"""Tests for src/capture/budget.py. Hermetic: every read goes to a tempfile
credit-log store and a tempfile families config, never to
data/processed/credit_log.jsonl or config/capture_families.json."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.capture import budget
from src.pipeline import creditlog

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _write_families(folder, families):
    path = Path(folder) / "capture_families.json"
    path.write_text(json.dumps({"families": families}), encoding="utf-8")
    return path


class EnvelopeArithmeticTests(unittest.TestCase):
    def test_daily_envelope_is_derived_from_the_tier_fact(self):
        # 100,000 allotment x 0.27 target / 30-day cycle = 900.
        self.assertEqual(budget.MONTHLY_ALLOTMENT, 100_000)
        self.assertEqual(
            budget.DAILY_ENVELOPE,
            round(budget.MONTHLY_ALLOTMENT * budget.UTILIZATION_TARGET
                  / budget.RESET_CYCLE_DAYS))
        self.assertEqual(budget.DAILY_ENVELOPE, 900)

    def test_credit_floor_is_not_duplicated(self):
        from src.pipeline import prop_listing
        self.assertIs(budget.CREDIT_FLOOR, prop_listing.CREDIT_FLOOR)
        self.assertEqual(budget.CREDIT_FLOOR, 5000)


class QuotaResetTests(unittest.TestCase):
    def test_reset_is_the_first_of_next_utc_month(self):
        moment = dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc)
        self.assertEqual(budget.quota_reset_utc(moment),
                          dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))

    def test_reset_boundary_rolls_over_the_year(self):
        moment = dt.datetime(2026, 12, 20, tzinfo=dt.timezone.utc)
        self.assertEqual(budget.quota_reset_utc(moment),
                          dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc))

    def test_days_until_reset_is_never_negative(self):
        # The last instant of the month: still >= 0 days out.
        moment = dt.datetime(2026, 9, 30, 23, 59, tzinfo=dt.timezone.utc)
        self.assertGreaterEqual(budget.days_until_reset(moment), 0)


class SpentTodayTests(unittest.TestCase):
    def test_spend_sums_consecutive_drops_within_the_day(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(1000, 0, "a", store=store, now=NOW)
            creditlog.log(994, 6, "b", store=store,
                          now=NOW + dt.timedelta(hours=1))
            creditlog.log(991, 3, "c", store=store,
                          now=NOW + dt.timedelta(hours=2))
            spent = budget.spent_today(now=NOW + dt.timedelta(hours=3), store=store)
        self.assertEqual(spent, 9)

    def test_a_reset_boundary_contributes_zero_not_a_negative_number(self):
        # remaining RISES between two readings -- the flow reset mid-day
        # (or between days). That jump must never read as negative spend.
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(50, 5, "a", store=store, now=NOW)
            creditlog.log(100_000, 0, "b", store=store,
                          now=NOW + dt.timedelta(hours=1))
            creditlog.log(99_994, 6, "c", store=store,
                          now=NOW + dt.timedelta(hours=2))
            spent = budget.spent_today(now=NOW + dt.timedelta(hours=3), store=store)
        # Only the second-to-third delta (6) counts; the reset jump counts as 0.
        self.assertEqual(spent, 6)

    def test_a_day_with_no_rows_spends_zero_not_none(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            self.assertEqual(budget.spent_today(now=NOW, store=store), 0)

    def test_remaining_today_is_none_without_a_row_for_today(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(500, 1, "a", store=store,
                          now=NOW - dt.timedelta(days=1))
            self.assertIsNone(budget.remaining_today(now=NOW, store=store))

    def test_remaining_today_is_the_latest_reading_for_today(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(500, 1, "a", store=store, now=NOW)
            creditlog.log(497, 3, "b", store=store,
                          now=NOW + dt.timedelta(minutes=5))
            self.assertEqual(budget.remaining_today(now=NOW, store=store), 497)


class FamilyCostTests(unittest.TestCase):
    def test_an_unmeasured_family_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_families(folder, {
                "alpha": {"measured": False, "credits_per_event": None}})
            self.assertIsNone(budget.family_cost("alpha", path=path))

    def test_a_measured_family_returns_its_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_families(folder, {
                "alpha": {"measured": True, "credits_per_event": 3}})
            self.assertEqual(budget.family_cost("alpha", path=path), 3)

    def test_a_missing_config_reads_as_unmeasured_not_a_crash(self):
        missing = Path("/nonexistent/nope/capture_families.json")
        self.assertIsNone(budget.family_cost("featured", path=missing))
        self.assertEqual(budget.load_families(path=missing), {})


class CanSpendTests(unittest.TestCase):
    def _families(self, folder):
        return _write_families(folder, {
            "featured": {"measured": True, "credits_per_event": 3},
            "team_totals": {"measured": False, "credits_per_event": None},
            "batter_props_floor": {"measured": False, "credits_per_event": None},
        })

    def test_the_floor_refuses_even_a_measured_family(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            decision = budget.can_spend(
                "featured", 3, remaining=budget.CREDIT_FLOOR + 1,
                spent=0, families_path=path)
        self.assertFalse(decision.allowed)
        self.assertIn("credit floor", decision.reason)

    def test_the_envelope_refuses_a_measured_family_over_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            decision = budget.can_spend(
                "featured", 3, remaining=99_000,
                spent=budget.DAILY_ENVELOPE, families_path=path)
        self.assertFalse(decision.allowed)
        self.assertIn("daily envelope", decision.reason)

    def test_a_measured_family_inside_floor_and_envelope_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            decision = budget.can_spend(
                "featured", 3, remaining=99_000, spent=0, families_path=path)
        self.assertTrue(decision.allowed)

    def test_an_unmeasured_family_is_probe_required_even_inside_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            decision = budget.can_spend(
                "team_totals", 1, remaining=99_000, spent=0, families_path=path)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))

    def test_zero_credit_requests_never_hit_the_floor_or_envelope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_families(folder, {
                "weather": {"measured": True, "credits_per_event": 0}})
            decision = budget.can_spend(
                "weather", 0, remaining=None, spent=None, families_path=path)
        self.assertTrue(decision.allowed)

    def test_the_non_droppable_floor_is_never_gated_by_floor_or_envelope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            # remaining/spent deliberately omitted and would fail closed for
            # any other family -- the floor family must bypass that check.
            decision = budget.can_spend(
                budget.NON_DROPPABLE_FAMILY, 5, families_path=path)
        # Still PROBE_REQUIRED (unmeasured in this fixture), but crucially
        # NOT refused for "quota unreadable" or "credit floor".
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith("PROBE_REQUIRED"))

    def test_unreadable_remaining_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            with tempfile.TemporaryDirectory() as logdir:
                empty_log = Path(logdir) / "credit_log.jsonl"
                decision = budget.can_spend(
                    "featured", 3, now=NOW, store=empty_log, families_path=path)
        self.assertFalse(decision.allowed)
        self.assertIn("quota unreadable", decision.reason)


class DropOrderTests(unittest.TestCase):
    def test_batter_props_are_not_dropped_first(self):
        families = [d["family"] for d in budget.DROP_ORDER]
        self.assertNotEqual(families[0], "batter_props_extra")
        self.assertNotIn("batter_props", families[:2])

    def test_featured_tier_a_is_always_last(self):
        self.assertEqual(budget.DROP_ORDER[-1]["family"], "featured")

    def test_the_non_droppable_floor_never_appears_in_the_drop_order(self):
        families = [d["family"] for d in budget.DROP_ORDER]
        self.assertNotIn(budget.NON_DROPPABLE_FAMILY, families)

    def test_ranks_are_contiguous_and_ordered(self):
        ranks = [d["rank"] for d in budget.DROP_ORDER]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_a_simulated_over_envelope_day_drops_in_the_written_order_and_never_touches_featured(self):
        """Simulate a squeeze: spend against every droppable family in
        DROP_ORDER's order until the envelope is exhausted, using each
        family's own measured cost where available (else a nominal probe
        cost of 1, standing in for whatever a real probe would return).
        Featured must be the last family touched, and the non-droppable
        floor must never be asked to give anything up."""
        with tempfile.TemporaryDirectory() as folder:
            costs = {
                "parlay_sgp": 1, "prop_listing_feasibility": 1,
                "team_totals": 1, "alternates": 1, "pitcher_props": 1,
                "f5_trio": 1, "batter_props_extra": 1, "featured": 3,
            }
            path = _write_families(folder, {
                name: {"measured": True, "credits_per_event": cost}
                for name, cost in costs.items()
            })
            spent = 0
            dropped_order = []
            remaining_budget = budget.DAILY_ENVELOPE
            for entry in budget.DROP_ORDER:
                family = entry["family"]
                cost = costs[family]
                # Keep spending this family until the envelope refuses it.
                while True:
                    decision = budget.can_spend(
                        family, cost, remaining=99_000, spent=spent, families_path=path)
                    if not decision.allowed:
                        dropped_order.append(family)
                        break
                    spent += cost
            # Every family eventually gets dropped once the envelope is
            # exhausted; featured must be the LAST one to run out of room.
            self.assertEqual(dropped_order[-1], "featured")
            self.assertLessEqual(spent, budget.DAILY_ENVELOPE)


class RotatedFloorGamesTests(unittest.TestCase):
    def test_selection_is_deterministic_for_the_same_date(self):
        games = ["g1", "g2", "g3", "g4", "g5"]
        first = budget.rotated_floor_games(games, "2026-09-03")
        second = budget.rotated_floor_games(games, "2026-09-03")
        self.assertEqual(first, second)

    def test_selection_picks_the_configured_count(self):
        games = ["g1", "g2", "g3", "g4", "g5"]
        chosen = budget.rotated_floor_games(games, "2026-09-03")
        self.assertEqual(len(chosen), budget.NON_DROPPABLE_GAMES_PER_NIGHT)

    def test_selection_rotates_across_different_dates(self):
        games = [f"g{i}" for i in range(10)]
        a = budget.rotated_floor_games(games, "2026-09-03")
        b = budget.rotated_floor_games(games, "2026-09-04")
        self.assertNotEqual(a, b)

    def test_an_empty_slate_selects_nothing(self):
        self.assertEqual(budget.rotated_floor_games([], "2026-09-03"), [])


class StatusTests(unittest.TestCase):
    def test_status_never_raises_with_a_missing_config_or_log(self):
        with tempfile.TemporaryDirectory() as folder:
            missing_log = Path(folder) / "credit_log.jsonl"
            missing_families = Path(folder) / "capture_families.json"
            result = budget.status(now=NOW, store=missing_log,
                                    families_path=missing_families)
        self.assertEqual(result["remaining_today"], None)
        self.assertEqual(result["spent_today"], 0)
        self.assertEqual(result["families"], {})


if __name__ == "__main__":
    unittest.main()
