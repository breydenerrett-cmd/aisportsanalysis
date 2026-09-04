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


class _FakeOddsProvider:
    """Minimal odds_provider stand-in for probe_family: no network, ever."""

    class OddsProviderError(RuntimeError):
        pass

    BATTER_MARKETS = ("batter_hits", "batter_total_bases", "batter_home_runs",
                       "batter_rbis", "batter_runs_scored", "batter_hits_runs_rbis")
    PROP_MARKETS = ("pitcher_strikeouts",)
    TEAM_TOTALS_MARKETS = ("team_totals",)
    ALTERNATE_MARKETS = ("alternate_spreads", "alternate_totals")
    EVENT_MARKETS = ("h2h_1st_5_innings", "spreads_1st_5_innings",
                      "totals_1st_5_innings")

    def __init__(self, remaining_before=53000, billed=6, remaining_after=None,
                 events=None, fail_fetch=None, configured=True, payload=None):
        self.remaining_before = remaining_before
        self.billed = billed
        self.remaining_after = (remaining_after if remaining_after is not None
                                 else remaining_before - billed)
        self.events = events if events is not None else [
            {"id": "g1", "commence_time": "2026-09-10T23:00:00Z"}]
        self.fail_fetch = fail_fetch
        self.configured = configured
        self.payload = payload  # None => build a healthy default per call
        self.calls = []

    def status(self, env=None):
        return {"configured": self.configured}

    def quota(self, env=None):
        return {"remaining": self.remaining_before, "last": 1}

    def list_events(self, env=None):
        return self.events

    def fetch_event_odds_with_usage(self, event_id, markets=None, env=None):
        self.calls.append((event_id, tuple(markets or ())))
        if self.fail_fetch:
            raise self.OddsProviderError(self.fail_fetch)
        if self.payload is not None:
            payload = self.payload
        else:
            # Healthy default: 2 books, each offering every requested
            # market with one outcome -- non-degenerate unless a test
            # explicitly asks for a thin `payload` instead.
            market_list = list(markets or ())
            book = {"markets": [{"key": m, "outcomes": [{"name": "x", "price": 100}]}
                                 for m in market_list]}
            payload = {"id": event_id, "bookmakers": [dict(book, key="book_a"),
                                                       dict(book, key="book_b")]}
        return (payload,
                {"remaining": self.remaining_after, "used": 1, "last": self.billed})


class ProbeFamilyTests(unittest.TestCase):
    def _families(self, folder, extra=None):
        families = {"batter_props_floor": {"measured": False,
                                            "credits_per_event": None,
                                            "measured_utc": None}}
        if extra:
            families.update(extra)
        return _write_families(folder, families)

    def test_a_real_probe_measures_and_records_the_credit_delta(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider(remaining_before=53000, billed=6)
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
            self.assertTrue(result["probed"])
            self.assertEqual(result["credits_per_event"], 6)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(provider.calls[0][0], "g1")
            self.assertEqual(set(provider.calls[0][1]), set(provider.BATTER_MARKETS))
            recorded = json.loads(path.read_text(encoding="utf-8"))
            entry = recorded["families"]["batter_props_floor"]
            self.assertTrue(entry["measured"])
            self.assertEqual(entry["credits_per_event"], 6)

    def test_a_second_probe_the_same_utc_day_is_refused_without_spending(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider()
            budget.probe_family("batter_props_floor", provider=provider,
                                 now=NOW, families_path=path)
            second = budget.probe_family(
                "batter_props_floor", provider=provider,
                now=NOW + dt.timedelta(hours=2), families_path=path)
        self.assertFalse(second["probed"])
        self.assertIn("already probed today", second["error"])
        self.assertEqual(len(provider.calls), 1)  # no second fetch

    def test_a_probe_the_next_utc_day_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider()
            budget.probe_family("batter_props_floor", provider=provider,
                                 now=NOW, families_path=path)
            second = budget.probe_family(
                "batter_props_floor", provider=provider,
                now=NOW + dt.timedelta(days=1), families_path=path)
        self.assertTrue(second["probed"])
        self.assertEqual(len(provider.calls), 2)

    def test_the_credit_floor_refuses_the_probe_before_any_spend(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider(remaining_before=budget.CREDIT_FLOOR)
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
        self.assertFalse(result["probed"])
        self.assertEqual(result["error"], "credit floor")
        self.assertEqual(provider.calls, [])

    def test_an_unknown_family_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider()
            result = budget.probe_family(
                "not_a_real_family", provider=provider, now=NOW, families_path=path)
        self.assertFalse(result["probed"])
        self.assertIn("unknown family", result["error"])

    def test_a_family_with_no_known_market_list_is_refused_not_guessed(self):
        # parlay_sgp has no odds_provider endpoint at all (confirmed
        # 2026-09-03, docs/SGP_PARLAY_CAPTURE.md) -- unlike team_totals,
        # alternates and f5_trio, which are wired below.
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder, extra={
                "parlay_sgp": {"measured": False, "credits_per_event": None,
                                "measured_utc": None}})
            provider = _FakeOddsProvider()
            result = budget.probe_family(
                "parlay_sgp", provider=provider, now=NOW, families_path=path)
        self.assertFalse(result["probed"])
        self.assertIn("not wired", result["error"])
        self.assertEqual(provider.calls, [])

    def test_team_totals_alternates_and_f5_trio_are_wired_to_the_right_markets(self):
        cases = (
            ("team_totals", ("team_totals",)),
            ("alternates", ("alternate_spreads", "alternate_totals")),
            ("f5_trio", ("h2h_1st_5_innings", "spreads_1st_5_innings",
                         "totals_1st_5_innings")),
        )
        for family, expected_markets in cases:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as folder:
                path = self._families(folder, extra={
                    family: {"measured": False, "credits_per_event": None,
                             "measured_utc": None}})
                provider = _FakeOddsProvider()
                result = budget.probe_family(
                    family, provider=provider, now=NOW, families_path=path)
                self.assertTrue(result["probed"], result)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(set(provider.calls[0][1]), set(expected_markets))
                self.assertIn("payload_shape", result)
                self.assertIn("degenerate", result)

    def test_a_failed_fetch_is_reported_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            provider = _FakeOddsProvider(fail_fetch="boom")
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
            self.assertFalse(result["probed"])
            self.assertIn("probe fetch failed", result["error"])
            recorded = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(recorded["families"]["batter_props_floor"]["measured"])

    def test_the_earliest_future_event_past_the_lead_time_is_chosen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            events = [
                {"id": "too_soon", "commence_time": "2026-09-03T12:30:00Z"},  # 30min out
                {"id": "later", "commence_time": "2026-09-04T01:00:00Z"},
                {"id": "earliest_eligible", "commence_time": "2026-09-03T13:00:00Z"},
            ]
            provider = _FakeOddsProvider(events=events)
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
        self.assertTrue(result["probed"])
        self.assertEqual(result["event_id"], "earliest_eligible")

    def test_refuses_and_spends_nothing_when_no_event_has_enough_lead_time(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            events = [{"id": "already_started", "commence_time": "2026-09-03T11:59:00Z"},
                      {"id": "too_soon", "commence_time": "2026-09-03T12:10:00Z"}]
            provider = _FakeOddsProvider(events=events)
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
            recorded = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(result["probed"])
        self.assertIn("commence_time", result["error"])
        self.assertEqual(provider.calls, [])  # no paid fetch happened
        self.assertFalse(recorded["families"]["batter_props_floor"]["measured"])

    def test_a_thin_payload_is_recorded_degenerate_and_does_not_satisfy_probe_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            thin_payload = {"id": "g1", "bookmakers": [
                {"key": "book_a", "markets": [
                    {"key": "batter_home_runs", "outcomes": [{"name": "x", "price": 100}]}]}]}
            provider = _FakeOddsProvider(payload=thin_payload)
            result = budget.probe_family(
                "batter_props_floor", provider=provider, now=NOW, families_path=path)
            recorded = json.loads(path.read_text(encoding="utf-8"))
            cost = budget.family_cost("batter_props_floor", path=path)
        self.assertTrue(result["probed"])
        self.assertTrue(result["degenerate"])
        entry = recorded["families"]["batter_props_floor"]
        self.assertTrue(entry["degenerate"])
        self.assertIsNone(cost)

    def test_a_degenerate_probe_does_not_block_a_same_day_reprobe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            thin_payload = {"id": "g1", "bookmakers": [
                {"key": "book_a", "markets": [
                    {"key": "batter_home_runs", "outcomes": [{"name": "x", "price": 100}]}]}]}
            provider = _FakeOddsProvider(payload=thin_payload)
            budget.probe_family("batter_props_floor", provider=provider,
                                 now=NOW, families_path=path)
            second = budget.probe_family(
                "batter_props_floor", provider=provider,
                now=NOW + dt.timedelta(hours=1), families_path=path)
        self.assertTrue(second["probed"])
        self.assertEqual(len(provider.calls), 2)

    def test_a_good_probe_blocks_a_same_day_reprobe_even_after_a_prior_degenerate_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._families(folder)
            thin_payload = {"id": "g1", "bookmakers": [
                {"key": "book_a", "markets": [
                    {"key": "batter_home_runs", "outcomes": [{"name": "x", "price": 100}]}]}]}
            provider = _FakeOddsProvider(payload=thin_payload)
            budget.probe_family("batter_props_floor", provider=provider,
                                 now=NOW, families_path=path)
            provider.payload = None  # next call gets the healthy default
            good = budget.probe_family(
                "batter_props_floor", provider=provider,
                now=NOW + dt.timedelta(hours=1), families_path=path)
            self.assertTrue(good["probed"])
            self.assertFalse(good["degenerate"])
            blocked = budget.probe_family(
                "batter_props_floor", provider=provider,
                now=NOW + dt.timedelta(hours=2), families_path=path)
            cost = budget.family_cost("batter_props_floor", path=path)
        self.assertFalse(blocked["probed"])
        self.assertIn("already probed today", blocked["error"])
        self.assertEqual(len(provider.calls), 2)  # no third fetch
        self.assertIsNotNone(cost)


class BandSeparationTests(unittest.TestCase):
    """Regression guard for the 2026-09-04 outage: an owner-approved
    ~47,000-credit HISTORICAL purchase, logged the same UTC day under its
    own (non-capture) caller, made `spent_today()` read as LIVE-CAPTURE
    spend and tripped the 900/day envelope on every real fetch for hours.
    `capture_spent_today()`/`can_spend()` must count only CAPTURE_CALLERS
    rows against the envelope -- while `spent_today()` (no filter) keeps
    reporting the whole day's real spend, historical band included."""

    def _families(self, folder):
        return _write_families(folder, {
            "featured": {"measured": True, "credits_per_event": 3}})

    def test_a_large_same_day_historical_spend_does_not_block_capture(self):
        # Realistic log rows for the exact scenario that just occurred:
        # capture checks in the morning, then one big historical purchase
        # logged under its own caller, then capture checks in again later.
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            families = self._families(folder)
            t = NOW
            creditlog.log(99365, 0, "dense.run", store=store, now=t)
            t += dt.timedelta(minutes=20)
            creditlog.log(99351, 0, "prop_listing.run", store=store, now=t)
            t += dt.timedelta(minutes=40)
            # The historical purchase: ~47,000 credits, logged under its own
            # caller -- not a capture caller.
            creditlog.log(52351, 47000, "probe_historical_f5_props.postflight",
                          store=store, now=t)
            t += dt.timedelta(minutes=30)
            creditlog.log(52348, 0, "dense.run", store=store, now=t)

            # Reported total spend still includes the historical purchase --
            # this is about which band the ENVELOPE reads, not hiding spend.
            self.assertEqual(budget.spent_today(now=t, store=store), 47017)
            # But the live-capture band's own spend is only the drops
            # revealed by CAPTURE-band rows: 14 (dense.run -> prop_listing.run)
            # + 3 (the historical row's checkpoint -> dense.run's next read).
            # The historical row's own 47,000-credit drop is excluded because
            # IT logged its own checkpoint and is bucketed there instead.
            self.assertEqual(budget.capture_spent_today(now=t, store=store), 17)

            decision = budget.can_spend("featured", 3, remaining=52348,
                                         now=t, store=store, families_path=families)
        self.assertTrue(decision.allowed, decision.reason)

    def test_a_large_same_day_capture_spend_still_blocks_capture(self):
        # The envelope must keep doing its actual job: a capture-band spend
        # that itself blows through DAILY_ENVELOPE is still refused. Tagged
        # budget_band=LIVE_CAPTURE explicitly, exactly as every real
        # dense.run/prop_listing.run/etc. call does post-fix -- an explicit
        # tag is authoritative and is never subject to the envelope-ceiling
        # reclassification `_delta_band()` applies ONLY to legacy,
        # untagged rows (see that function's docstring: the ceiling can
        # only ever move a legacy row AWAY from live_capture, and only
        # because it has no explicit tag to trust in the first place).
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            families = self._families(folder)
            t = NOW
            creditlog.log(99365, 0, "dense.run", store=store, now=t,
                          budget_band=budget.LIVE_CAPTURE)
            t += dt.timedelta(minutes=20)
            # 950 credits of CAPTURE-band spend in one step -- over the
            # 900/day envelope on its own, no historical purchase involved.
            creditlog.log(98415, 950, "prop_listing.run", store=store, now=t,
                          budget_band=budget.LIVE_CAPTURE)

            self.assertEqual(budget.capture_spent_today(now=t, store=store), 950)

            decision = budget.can_spend("featured", 3, remaining=98415,
                                         now=t, store=store, families_path=families)
        self.assertFalse(decision.allowed)
        self.assertIn("daily envelope", decision.reason)

    def test_historical_only_rows_never_enter_capture_spend(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            t = NOW
            creditlog.log(99365, 0, "probe_historical_boundaries.preflight",
                          store=store, now=t)
            t += dt.timedelta(minutes=5)
            creditlog.log(50000, 49365, "probe_historical_boundaries.back_2023",
                          store=store, now=t)
            self.assertEqual(budget.capture_spent_today(now=t, store=store), 0)
            self.assertEqual(budget.spent_today(now=t, store=store), 49365)

    def test_an_unlogged_historical_spend_is_still_excluded_via_the_envelope_ceiling(self):
        # The REAL 2026-09-04 shape, reproduced exactly: the historical
        # process that drained ~47,000 credits never called
        # `creditlog.log()` at all (src/pipeline/backfill.py and whatever
        # ran the T-2h F5 normalization have no creditlog import), so there
        # is no row -- explicit band or legacy caller -- for anything to
        # classify. Only the NEXT live-capture checkpoint reveals the drop,
        # as an old (pre-fix), unbanded row. `_delta_band()`'s envelope
        # ceiling is what actually saves this case: `can_spend()` could
        # never have approved a single live-capture delta this large, so it
        # is excluded from `capture_spent_today()` regardless of which
        # capture caller happened to log next.
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            families = self._families(folder)
            t = NOW
            creditlog.log(72931, 0, "derivative_markets.run", store=store, now=t)
            t += dt.timedelta(hours=2)
            # No row at all for the historical run in between -- exactly
            # the real incident. The next capture checkpoint just observes
            # a huge drop with nothing to explain it.
            creditlog.log(25707, 0, "dense.run", store=store, now=t)

            self.assertEqual(budget.spent_today(now=t, store=store), 47224)
            self.assertEqual(budget.capture_spent_today(now=t, store=store), 0)

            decision = budget.can_spend("featured", 3, remaining=25707,
                                         now=t, store=store, families_path=families)
        self.assertTrue(decision.allowed, decision.reason)

    def test_an_explicit_budget_band_wins_over_the_caller_name(self):
        # Owner amendment: classification must be explicit and durable, not
        # inferred from a caller string. A row that DECLARES itself
        # historical_backfill is excluded from the envelope even though its
        # caller string would otherwise read as a capture caller under the
        # legacy fallback -- the explicit field is authoritative.
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            t = NOW
            creditlog.log(99365, 0, "dense.run", store=store, now=t,
                          budget_band=budget.LIVE_CAPTURE)
            t += dt.timedelta(minutes=30)
            # Same caller string as a real capture call, but explicitly
            # tagged historical_backfill -- e.g. a one-off recovery/backfill
            # invocation that reused the module. The field, not the name,
            # decides.
            creditlog.log(52365, 47000, "dense.run", store=store, now=t,
                          budget_band=budget.HISTORICAL_BACKFILL)
            self.assertEqual(budget.capture_spent_today(now=t, store=store), 0)
            self.assertEqual(budget.spent_today(now=t, store=store), 47000)

    def test_an_explicit_test_band_is_excluded_from_the_envelope(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            t = NOW
            creditlog.log(1000, 0, "some_fixture", store=store, now=t,
                          budget_band=budget.TEST)
            t += dt.timedelta(minutes=5)
            creditlog.log(1, 999, "some_fixture", store=store, now=t,
                          budget_band=budget.TEST)
            self.assertEqual(budget.capture_spent_today(now=t, store=store), 0)

    def test_row_band_prefers_the_explicit_field(self):
        self.assertEqual(
            budget.row_band({"caller": "probe_historical_f5_props.postflight",
                              "budget_band": "live_capture"}),
            "live_capture")

    def test_row_band_falls_back_deterministically_for_legacy_rows(self):
        # No "budget_band" key at all -- every row logged before this field
        # existed. The fallback must be a pure function of `caller`.
        self.assertEqual(
            budget.row_band({"caller": "dense.run"}), budget.LIVE_CAPTURE)
        self.assertEqual(
            budget.row_band({"caller": "prop_prices.run"}), budget.LIVE_CAPTURE)
        self.assertEqual(
            budget.row_band({"caller": "budget.probe_family:pitcher_props"}),
            budget.PROBE)
        self.assertEqual(
            budget.row_band({"caller": "probe_historical_f5_props.postflight"}),
            budget.HISTORICAL_BACKFILL)
        # An unrecognized future caller, and a missing/empty caller, both
        # default to historical_backfill -- never silently live_capture.
        self.assertEqual(
            budget.row_band({"caller": "some_new_unrecognized_caller"}),
            budget.HISTORICAL_BACKFILL)
        self.assertEqual(budget.row_band({}), budget.HISTORICAL_BACKFILL)
        # Deterministic: same input, same output, called twice.
        row = {"caller": "dense.run"}
        self.assertEqual(budget.row_band(row), budget.row_band(row))

    def test_an_invalid_budget_band_value_falls_back_to_legacy_classification(self):
        # A corrupt or unrecognized value in the field must not be trusted
        # blindly -- fall back to the deterministic caller classifier rather
        # than accept an arbitrary string as a real band.
        self.assertEqual(
            budget.row_band({"caller": "dense.run", "budget_band": "made_up"}),
            budget.LIVE_CAPTURE)

    def test_capture_callers_matches_the_real_logging_callers(self):
        # Pinned so a renamed/added caller in one of the five paid-capture
        # modules is a reviewable diff here, not a silent re-widening of
        # what counts against the live-capture envelope.
        self.assertEqual(budget.CAPTURE_CALLERS, frozenset({
            "dense.run", "dense.close_capture",
            "prop_listing.run", "prop_prices.run",
            "batter_props.run", "derivative_markets.run",
        }))


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
