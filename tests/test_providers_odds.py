"""Tests for src/providers/odds.py. No network, no real key.

Two behaviours matter most: the key never appears in any output, and a missing
market stays missing rather than acquiring a substitute price.
"""

import json
import unittest
from unittest import mock

from src.providers import odds
from src.providers.odds import NotConfigured, OddsProviderError

FAKE_KEY = "sk-not-a-real-key-abc123"


def event(home="Chicago White Sox", away="Toronto Blue Jays",
          books=None, event_id="evt1"):
    return {
        "id": event_id,
        "commence_time": "2025-07-09T18:10:00Z",
        "home_team": home,
        "away_team": away,
        "bookmakers": books if books is not None else [full_book()],
    }


def full_book(key="draftkings", home="Chicago White Sox",
              away="Toronto Blue Jays", home_price=-130, away_price=110):
    return {
        "key": key,
        "last_update": "2025-07-09T17:00:00Z",
        "markets": [
            {"key": "h2h", "outcomes": [
                {"name": home, "price": home_price},
                {"name": away, "price": away_price},
            ]},
            {"key": "spreads", "outcomes": [
                {"name": home, "price": 150, "point": -1.5},
                {"name": away, "price": -175, "point": 1.5},
            ]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "price": -110, "point": 8.5},
                {"name": "Under", "price": -110, "point": 8.5},
            ]},
        ],
    }


class TestConfiguration(unittest.TestCase):
    def test_not_configured_without_a_key(self):
        self.assertFalse(odds.is_configured({}))
        self.assertIsNone(odds.api_key({}))

    def test_blank_key_counts_as_missing(self):
        self.assertFalse(odds.is_configured({"ODDS_API_KEY": "   "}))

    def test_configured_with_a_key(self):
        self.assertTrue(odds.is_configured({"ODDS_API_KEY": FAKE_KEY}))

    def test_status_succeeds_without_a_key(self):
        result = odds.status({})
        self.assertFalse(result["configured"])
        self.assertIn("the-odds-api.com", result["message"])

    def test_status_never_contains_the_key(self):
        result = odds.status({"ODDS_API_KEY": FAKE_KEY, "DEFAULT_BOOK": "fanduel"})
        self.assertNotIn(FAKE_KEY, repr(result))
        self.assertTrue(result["configured"])
        self.assertEqual(result["default_book"], "fanduel")

    def test_status_reports_all_three_markets(self):
        self.assertEqual(sorted(odds.status({})["markets"]),
                         ["h2h", "spreads", "totals"])


class TestConfiguredMarkets(unittest.TestCase):
    """ODDS_API_MARKETS was advertised in .env.example from the start and never
    read, so every call spent 3 credits whether or not 3 markets were wanted --
    and credits-per-call is the input that picks the snapshot cadence."""

    def test_default_is_all_three_markets(self):
        self.assertEqual(odds.configured_markets({}), ["h2h", "spreads", "totals"])

    def test_env_narrows_the_markets(self):
        self.assertEqual(odds.configured_markets({"ODDS_API_MARKETS": "h2h"}),
                         ["h2h"])

    def test_whitespace_is_tolerated(self):
        self.assertEqual(
            odds.configured_markets({"ODDS_API_MARKETS": " h2h , totals "}),
            ["h2h", "totals"])

    def test_an_unsupported_market_is_rejected(self):
        with self.assertRaises(OddsProviderError):
            odds.configured_markets({"ODDS_API_MARKETS": "h2h,player_props"})

    def test_the_request_asks_only_for_configured_markets(self):
        env = {"ODDS_API_KEY": FAKE_KEY, "ODDS_API_MARKETS": "h2h"}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_odds(env=env)
        self.assertEqual(fake.call_args[0][1]["markets"], "h2h")

    def test_credit_estimate_follows_the_configuration(self):
        one = odds.estimate_credits(env={"ODDS_API_MARKETS": "h2h"})
        three = odds.estimate_credits(env={})
        self.assertEqual(one["credits_per_call"], 1)
        self.assertEqual(three["credits_per_call"], 3)

    def test_narrowing_markets_triples_the_affordable_cadence(self):
        # The practical consequence: one market fits a far denser schedule.
        one = odds.recommend_live_schedule(daily_snapshots=12,
                                           env={"ODDS_API_MARKETS": "h2h"})
        three = odds.recommend_live_schedule(daily_snapshots=12, env={})
        self.assertTrue(one["fits_free_tier"])
        self.assertFalse(three["fits_free_tier"])

    def test_status_reports_the_configured_markets(self):
        self.assertEqual(odds.status({"ODDS_API_MARKETS": "h2h"})["markets"],
                         ["h2h"])


class TestConfiguredOddsFormat(unittest.TestCase):
    def test_default_is_american(self):
        self.assertEqual(odds.configured_odds_format({}), "american")

    def test_american_is_accepted(self):
        self.assertEqual(
            odds.configured_odds_format({"ODDS_API_ODDS_FORMAT": "American"}),
            "american")

    def test_decimal_is_rejected_loudly(self):
        # Every conversion downstream assumes American. A decimal price read as
        # American would be silently, catastrophically wrong rather than an error.
        with self.assertRaises(OddsProviderError) as ctx:
            odds.configured_odds_format({"ODDS_API_ODDS_FORMAT": "decimal"})
        self.assertIn("silently wrong", str(ctx.exception))


class TestFailSafe(unittest.TestCase):
    def test_fetch_without_key_raises_not_configured(self):
        with self.assertRaises(NotConfigured) as ctx:
            odds.fetch_odds(env={})
        self.assertIn("the-odds-api.com", str(ctx.exception))

    def test_not_configured_message_contains_no_key(self):
        with self.assertRaises(NotConfigured) as ctx:
            odds.fetch_odds(env={})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_not_configured_is_an_odds_provider_error(self):
        self.assertTrue(issubclass(NotConfigured, OddsProviderError))


class TestKeyNeverLeaks(unittest.TestCase):
    """The key travels as a query parameter, so any error text that includes
    the URL would leak it into logs and stack traces."""

    @staticmethod
    def http_error(code):
        import urllib.error
        return urllib.error.HTTPError(
            f"https://api.the-odds-api.com/v4/x?apiKey={FAKE_KEY}",
            code, "err", None, None)

    def test_401_message_excludes_the_key(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(401)):
            with self.assertRaises(OddsProviderError) as ctx:
                odds.fetch_odds(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertIn("401", str(ctx.exception))

    def test_429_message_excludes_the_key_and_mentions_quota(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(429)):
            with self.assertRaises(OddsProviderError) as ctx:
                odds.fetch_odds(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertIn("quota", str(ctx.exception))

    def test_generic_http_error_excludes_the_key(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(503)):
            with self.assertRaises(OddsProviderError) as ctx:
                odds.fetch_odds(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertNotIn(FAKE_KEY, str(ctx.exception))

    def test_key_is_not_in_the_exception_chain(self):
        # `raise ... from None` suppresses the original, which carried the URL.
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(401)):
            try:
                odds.fetch_odds(env={"ODDS_API_KEY": FAKE_KEY})
            except OddsProviderError as exc:
                self.assertIsNone(exc.__cause__)


class TestCreditEstimation(unittest.TestCase):
    def test_three_markets_one_region_costs_three(self):
        estimate = odds.estimate_credits(("h2h", "spreads", "totals"), ("us",))
        self.assertEqual(estimate["credits_per_call"], 3)

    def test_single_market_costs_one(self):
        self.assertEqual(odds.estimate_credits(("h2h",), ("us",))["credits_per_call"], 1)

    def test_two_regions_double_the_cost(self):
        estimate = odds.estimate_credits(("h2h",), ("us", "eu"))
        self.assertEqual(estimate["credits_per_call"], 2)

    def test_free_tier_exhaustion_is_reported(self):
        # 3 credits * 96 calls/day = 288/day; 500 free credits lasts under 2 days.
        estimate = odds.estimate_credits()
        self.assertEqual(estimate["credits_per_day_at_15min"], 288)
        self.assertLess(estimate["days_until_free_tier_exhausted"], 2.0)

    def test_unknown_market_rejected(self):
        with self.assertRaises(OddsProviderError):
            odds.estimate_credits(("h2h", "player_props"))

    def test_empty_markets_rejected(self):
        with self.assertRaises(OddsProviderError):
            odds.estimate_credits(())


class TestHistoricalBackfillEstimate(unittest.TestCase):
    """Historical odds are the one input with no free substitute. Pricing the
    backfill correctly is what turns 'can we backtest?' into a yes or no."""

    def test_historical_costs_ten_times_live(self):
        live = odds.estimate_credits(("h2h",), ("us",))["credits_per_call"]
        hist = odds.estimate_backfill_credits(markets=("h2h",),
                                              regions=("us",))["credits_per_call"]
        self.assertEqual(hist, live * odds.HISTORICAL_CREDIT_MULTIPLIER)

    def test_three_seasons_of_moneyline_fits_the_100k_plan(self):
        estimate = odds.estimate_backfill_credits(seasons=3, markets=("h2h",))
        self.assertEqual(estimate["total_credits"], 55_800)
        self.assertEqual(estimate["cheapest_plan"], "100K")
        self.assertEqual(estimate["one_time_cost_usd"], 59)

    def test_all_markets_three_seasons_needs_the_larger_plan(self):
        estimate = odds.estimate_backfill_credits(
            seasons=3, markets=("h2h", "spreads", "totals"))
        self.assertEqual(estimate["one_time_cost_usd"], 119)

    def test_cost_scales_linearly_with_seasons(self):
        one = odds.estimate_backfill_credits(seasons=1, markets=("h2h",))
        three = odds.estimate_backfill_credits(seasons=3, markets=("h2h",))
        self.assertEqual(three["total_credits"], one["total_credits"] * 3)

    def test_free_tier_never_covers_a_backfill(self):
        # Even the smallest useful backfill dwarfs 500 credits.
        estimate = odds.estimate_backfill_credits(seasons=1, markets=("h2h",),
                                                  snapshots_per_day=1)
        self.assertGreater(estimate["total_credits"], 500)

    def test_coverage_start_is_reported(self):
        # Nothing before this date exists, whatever you pay.
        self.assertEqual(
            odds.estimate_backfill_credits()["coverage_starts"], "2020-06-06")

    def test_invalid_inputs_rejected(self):
        for kwargs in ({"seasons": 0}, {"snapshots_per_day": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(OddsProviderError):
                    odds.estimate_backfill_credits(**kwargs)


class TestLiveScheduleRecommendation(unittest.TestCase):
    def test_four_snapshots_a_day_fits_the_free_tier(self):
        result = odds.recommend_live_schedule(daily_snapshots=4)
        self.assertTrue(result["fits_free_tier"])
        self.assertEqual(result["credits_per_month"], 360)

    def test_eight_snapshots_a_day_does_not_fit(self):
        self.assertFalse(
            odds.recommend_live_schedule(daily_snapshots=8)["fits_free_tier"])

    def test_fifteen_minute_polling_blows_the_budget_badly(self):
        # 96 polls/day is the naive "just poll constantly" schedule.
        result = odds.recommend_live_schedule(daily_snapshots=96)
        self.assertFalse(result["fits_free_tier"])
        self.assertLess(result["headroom"], -8000)

    def test_fewer_markets_allow_more_snapshots(self):
        many = odds.recommend_live_schedule(daily_snapshots=8, markets=("h2h",))
        self.assertTrue(many["fits_free_tier"])


class TestNormalization(unittest.TestCase):
    def test_all_three_markets_are_extracted(self):
        record = odds.normalize_event(event())
        self.assertEqual(sorted(record["markets"]), ["h2h", "spreads", "totals"])

    def test_moneyline_prices_map_to_the_right_sides(self):
        record = odds.normalize_event(event())
        self.assertEqual(record["markets"]["h2h"]["home_price"], -130)
        self.assertEqual(record["markets"]["h2h"]["away_price"], 110)

    def test_run_line_keeps_both_handicap_and_price(self):
        spreads = odds.normalize_event(event())["markets"]["spreads"]
        self.assertEqual(spreads["home_line"], -1.5)
        self.assertEqual(spreads["home_price"], 150)
        self.assertEqual(spreads["away_line"], 1.5)

    def test_total_keeps_the_number_and_both_prices(self):
        totals = odds.normalize_event(event())["markets"]["totals"]
        self.assertEqual(totals["total"], 8.5)
        self.assertEqual(totals["over_price"], -110)
        self.assertEqual(totals["under_price"], -110)

    def test_preferred_book_wins_when_it_offers_the_market(self):
        books = [full_book("fanduel", home_price=-140),
                 full_book("draftkings", home_price=-130)]
        record = odds.normalize_event(event(books=books),
                                      preferred_book="draftkings")
        self.assertEqual(record["markets"]["h2h"]["book"], "draftkings")
        self.assertEqual(record["markets"]["h2h"]["home_price"], -130)

    def test_falls_back_to_another_book_when_preferred_is_absent(self):
        record = odds.normalize_event(event(books=[full_book("fanduel")]),
                                      preferred_book="draftkings")
        self.assertEqual(record["markets"]["h2h"]["book"], "fanduel")

    def test_missing_market_is_absent_not_defaulted(self):
        book = full_book()
        book["markets"] = [m for m in book["markets"] if m["key"] != "totals"]
        record = odds.normalize_event(event(books=[book]))
        self.assertNotIn("totals", record["markets"])
        self.assertIn("h2h", record["markets"])

    def test_no_bookmakers_yields_no_markets_not_an_error(self):
        record = odds.normalize_event(event(books=[]))
        self.assertEqual(record["markets"], {})
        self.assertEqual(record["home_team"], "Chicago White Sox")

    def test_half_a_market_is_discarded_entirely(self):
        # One side priced, the other missing -- unusable, so nothing is kept.
        book = full_book()
        for market in book["markets"]:
            if market["key"] == "h2h":
                market["outcomes"] = [market["outcomes"][0]]
        record = odds.normalize_event(event(books=[book]))
        self.assertNotIn("h2h", record["markets"])

    def test_null_price_discards_the_market(self):
        book = full_book()
        for market in book["markets"]:
            if market["key"] == "h2h":
                market["outcomes"][0]["price"] = None
        self.assertNotIn("h2h", odds.normalize_event(event(books=[book]))["markets"])

    def test_total_without_a_point_is_discarded(self):
        book = full_book()
        for market in book["markets"]:
            if market["key"] == "totals":
                market["outcomes"][0].pop("point")
        self.assertNotIn("totals",
                         odds.normalize_event(event(books=[book]))["markets"])

    def test_team_name_mismatch_discards_rather_than_guessing(self):
        # If the book names a team differently, matching by position would be a
        # coin flip. Better to drop the market than to assign prices wrongly.
        book = full_book(home="Chicago Whitesox")
        self.assertNotIn("h2h", odds.normalize_event(event(books=[book]))["markets"])


class TestCoverage(unittest.TestCase):
    def setUp(self):
        # These tests exercise fetch_normalized's coverage math, not the raw
        # (L0) capture layer -- patch that write out so a real run of this
        # suite never touches the real data/raw/oddsapi directory.
        patcher = mock.patch.object(odds, "_write_raw_capture")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_coverage_counts_present_markets(self):
        with mock.patch.object(odds, "_get_json", return_value=[event(), event()]):
            result = odds.fetch_normalized(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["coverage"]["by_market"]["h2h"], 2)
        self.assertEqual(result["coverage"]["missing"]["totals"], 0)

    def test_coverage_surfaces_a_missing_market(self):
        book = full_book()
        book["markets"] = [m for m in book["markets"] if m["key"] != "spreads"]
        with mock.patch.object(odds, "_get_json",
                               return_value=[event(books=[book])]):
            result = odds.fetch_normalized(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertEqual(result["coverage"]["missing"]["spreads"], 1)

    def test_fetch_normalized_stamps_a_timestamp(self):
        with mock.patch.object(odds, "_get_json", return_value=[event()]):
            result = odds.fetch_normalized(env={"ODDS_API_KEY": FAKE_KEY})
        self.assertIn("fetched_utc", result)
        self.assertTrue(result["fetched_utc"].startswith("20"))

    def test_request_asks_for_all_three_markets(self):
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_odds(env={"ODDS_API_KEY": FAKE_KEY})
        params = fake.call_args[0][1]
        self.assertEqual(params["markets"], "h2h,spreads,totals")
        self.assertEqual(params["oddsFormat"], "american")


if __name__ == "__main__":
    unittest.main()


class TestFirstFiveMarkets(unittest.TestCase):
    """First-five markets are a different endpoint with a different billing shape.

    The trap this guards is a caller naming an F5 market on the featured endpoint.
    The live API answers 422 INVALID_MARKET -- but only AFTER the request is made,
    by which time credits for the rest of the batch are spent. It has to be caught
    before the call.
    """

    def test_f5_markets_are_nameable(self):
        for market in odds.EVENT_MARKETS:
            self.assertIn(market, odds.SUPPORTED_MARKETS)

    def test_f5_markets_are_not_requested_by_default(self):
        # Defaulting to them would silently multiply every snapshot's cost by the
        # size of the slate.
        for market in odds.EVENT_MARKETS:
            self.assertNotIn(market, odds.DEFAULT_MARKETS)

    def test_featured_endpoint_refuses_an_f5_market_before_spending_credits(self):
        with self.assertRaises(odds.OddsProviderError) as ctx:
            odds._validate_markets(["h2h", "totals_1st_5_innings"])
        self.assertIn("bills per event", str(ctx.exception))

    def test_event_endpoint_accepts_them(self):
        resolved = odds._validate_markets(
            ["h2h_1st_5_innings", "totals_1st_5_innings"], allow_event_markets=True)
        self.assertEqual(len(resolved), 2)

    def test_genuinely_unknown_markets_are_still_rejected(self):
        with self.assertRaises(odds.OddsProviderError):
            odds._validate_markets(["player_strikeouts"], allow_event_markets=True)

    def test_event_id_must_be_a_real_id(self):
        for bad in (None, "", 12345):
            with self.assertRaises(odds.OddsProviderError):
                odds.fetch_event_odds(bad, env={"ODDS_API_KEY": "x"})


class TestPerEventCreditMath(unittest.TestCase):
    """Per-event billing is linear in slate size; featured billing is flat.

    Confirmed against the live API: two markets on one event cost exactly 2 credits.
    """

    def test_cost_scales_with_the_number_of_events(self):
        two = odds.estimate_event_credits(
            16, markets=["h2h_1st_5_innings", "totals_1st_5_innings"])
        self.assertEqual(two["credits_per_event"], 2)
        self.assertEqual(two["credits_total"], 32)

    def test_a_full_slate_burns_a_free_month_in_about_fifteen_snapshots(self):
        est = odds.estimate_event_credits(
            16, markets=["h2h_1st_5_innings", "totals_1st_5_innings"])
        self.assertEqual(est["snapshots_per_free_month"], 15)

    def test_scanning_first_makes_it_affordable(self):
        # The whole reason the scanner's silence matters commercially: two flagged
        # games instead of sixteen turns fifteen snapshots a month into a hundred
        # and twenty-five.
        flagged = odds.estimate_event_credits(
            2, markets=["h2h_1st_5_innings", "totals_1st_5_innings"])
        self.assertEqual(flagged["credits_total"], 4)
        self.assertEqual(flagged["snapshots_per_free_month"], 125)

    def test_the_featured_comparison_is_reported_alongside(self):
        est = odds.estimate_event_credits(16)
        self.assertEqual(est["if_it_were_a_featured_call"], 3)
        self.assertEqual(est["credits_total"], 48)

    def test_zero_events_costs_nothing_and_does_not_divide_by_zero(self):
        est = odds.estimate_event_credits(0)
        self.assertEqual(est["credits_total"], 0)
        self.assertIsNone(est["snapshots_per_free_month"])

    def test_negative_events_is_an_error_not_a_credit(self):
        with self.assertRaises(odds.OddsProviderError):
            odds.estimate_event_credits(-3)


class TestFirstFiveNormalization(unittest.TestCase):
    """F5 markets reuse the full-game parsers rather than a copy that could drift."""

    EVENT = {
        "id": "abc", "home_team": "New York Yankees", "away_team": "Houston Astros",
        "commence_time": "2026-08-27T23:05:00Z",
        "bookmakers": [{
            "key": "fanduel", "last_update": "2026-08-27T22:14:07Z",
            "markets": [
                {"key": "h2h_1st_5_innings", "outcomes": [
                    {"name": "Houston Astros", "price": 138},
                    {"name": "New York Yankees", "price": -174}]},
                {"key": "totals_1st_5_innings", "outcomes": [
                    {"name": "Over", "price": -102, "point": 4.5},
                    {"name": "Under", "price": -128, "point": 4.5}]},
            ]}]}

    def test_f5_moneyline_is_flattened_like_a_full_game_moneyline(self):
        record = odds.normalize_event(self.EVENT)
        f5 = record["markets"]["h2h_1st_5_innings"]
        self.assertEqual(f5["home_price"], -174)
        self.assertEqual(f5["away_price"], 138)

    def test_f5_total_keeps_its_line(self):
        f5 = odds.normalize_event(self.EVENT)["markets"]["totals_1st_5_innings"]
        self.assertEqual(f5["total"], 4.5)
        self.assertEqual(f5["over_price"], -102)

    def test_full_game_markets_are_absent_rather_than_borrowed_from_f5(self):
        # The single most dangerous possible bug here: silently treating a first-five
        # total of 4.5 as a full-game total, which would look entirely plausible on
        # a screen and be wrong by four runs.
        record = odds.normalize_event(self.EVENT)
        self.assertNotIn("totals", record["markets"])
        self.assertNotIn("h2h", record["markets"])

    def test_a_half_filled_f5_market_is_dropped_not_partially_kept(self):
        event = json.loads(json.dumps(self.EVENT))
        event["bookmakers"][0]["markets"][1]["outcomes"][1].pop("price")
        record = odds.normalize_event(event)
        self.assertNotIn("totals_1st_5_innings", record["markets"])
        self.assertIn("h2h_1st_5_innings", record["markets"])


class TestConnectionFailuresAreCaught(unittest.TestCase):
    """A dropped connection is not a URLError, and it killed a live backfill.

    http.client.RemoteDisconnected inherits from ConnectionResetError and
    BadStatusLine, neither of which is urllib.error.URLError -- so it escaped the
    provider's handler entirely and took down a run that had already spent 30,000
    credits. Over a few hundred requests that is survivable; over the 1,800 a
    backfill makes it is a certainty.
    """

    def transport_error(self, exc):
        with mock.patch("urllib.request.urlopen", side_effect=exc):
            with self.assertRaises(odds.OddsProviderError) as ctx:
                odds._get_json("sports", {"apiKey": "x"})
        return str(ctx.exception)

    def test_a_dropped_connection_becomes_a_provider_error(self):
        import http.client
        message = self.transport_error(
            http.client.RemoteDisconnected("Remote end closed connection"))
        self.assertIn("connection failed", message)
        self.assertIn("RemoteDisconnected", message)

    def test_a_reset_connection_is_caught(self):
        self.assertIn("connection failed",
                      self.transport_error(ConnectionResetError("reset")))

    def test_a_timeout_is_caught(self):
        self.assertIn("connection failed", self.transport_error(TimeoutError()))

    def test_the_key_never_appears_in_a_connection_error(self):
        import http.client
        message = self.transport_error(http.client.BadStatusLine("junk"))
        self.assertNotIn("apiKey", message)

    def test_the_usage_seam_is_protected_too(self):
        import http.client
        with mock.patch("urllib.request.urlopen",
                        side_effect=http.client.RemoteDisconnected("x")):
            with self.assertRaises(odds.OddsProviderError):
                odds._get_json_with_usage("sports", {"apiKey": "x"})
