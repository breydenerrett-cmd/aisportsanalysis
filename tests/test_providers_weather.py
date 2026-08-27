"""Tests for src/providers/weather.py. No network -- _get_json is patched."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.providers import weather
from src.providers.weather import WeatherError


def hourly_payload(hours=None, temps=None, humidity=None,
                   winds=None, directions=None):
    """Build an Open-Meteo-shaped hourly response."""
    hours = hours or ["2025-07-09T17:00", "2025-07-09T18:00", "2025-07-09T19:00"]
    return {
        "hourly": {
            "time": hours,
            "temperature_2m": temps if temps is not None else [80.0, 82.3, 81.1],
            "relative_humidity_2m": humidity if humidity is not None else [70, 75, 72],
            "wind_speed_10m": winds if winds is not None else [4.0, 5.0, 6.0],
            "wind_direction_10m": (directions if directions is not None
                                   else [180, 200, 210]),
        }
    }


class TestExtractHour(unittest.TestCase):
    def test_picks_the_closest_hour_to_first_pitch(self):
        reading = weather.extract_hour(hourly_payload(), "2025-07-09T18:10:00Z")
        self.assertEqual(reading["observed_utc"], "2025-07-09T18:00")
        self.assertAlmostEqual(reading["temp_f"], 82.3)
        self.assertAlmostEqual(reading["wind_mph"], 5.0)
        self.assertEqual(reading["wind_from_deg"], 200)
        self.assertEqual(reading["humidity_pct"], 75)

    def test_rounds_to_the_nearer_hour_when_between(self):
        # 18:40 is closer to 19:00 than to 18:00.
        reading = weather.extract_hour(hourly_payload(), "2025-07-09T18:40:00Z")
        self.assertEqual(reading["observed_utc"], "2025-07-09T19:00")

    def test_reports_distance_from_first_pitch(self):
        reading = weather.extract_hour(hourly_payload(), "2025-07-09T18:30:00Z")
        self.assertAlmostEqual(reading["hours_from_first_pitch"], 0.5)

    def test_missing_field_is_none_not_zero(self):
        # Zero humidity is a real reading; absent data must not look like it.
        payload = hourly_payload()
        del payload["hourly"]["relative_humidity_2m"]
        reading = weather.extract_hour(payload, "2025-07-09T18:10:00Z")
        self.assertIsNone(reading["humidity_pct"])
        self.assertAlmostEqual(reading["temp_f"], 82.3)

    def test_short_series_does_not_index_out_of_range(self):
        payload = hourly_payload()
        payload["hourly"]["wind_speed_10m"] = [4.0]  # shorter than time series
        reading = weather.extract_hour(payload, "2025-07-09T19:00:00Z")
        self.assertIsNone(reading["wind_mph"])

    def test_null_value_in_series_is_preserved_as_none(self):
        payload = hourly_payload(temps=[80.0, None, 81.1])
        reading = weather.extract_hour(payload, "2025-07-09T18:10:00Z")
        self.assertIsNone(reading["temp_f"])

    def test_empty_response_raises(self):
        with self.assertRaises(WeatherError):
            weather.extract_hour({"hourly": {"time": []}}, "2025-07-09T18:00:00Z")

    def test_missing_hourly_block_raises(self):
        with self.assertRaises(WeatherError):
            weather.extract_hour({}, "2025-07-09T18:00:00Z")

    def test_unparseable_timestamps_raise(self):
        payload = {"hourly": {"time": ["not-a-time", "also-bad"]}}
        with self.assertRaises(WeatherError):
            weather.extract_hour(payload, "2025-07-09T18:00:00Z")


class TestEndpointSelection(unittest.TestCase):
    def test_old_game_uses_the_archive_endpoint(self):
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()) as fake:
            reading = weather.fetch_for_game(41.83, -87.63, old)
        self.assertEqual(fake.call_args[0][0], weather.ARCHIVE_HOST)
        self.assertEqual(reading["source"], "archive")

    def test_upcoming_game_uses_the_forecast_endpoint(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()) as fake:
            reading = weather.fetch_for_game(41.83, -87.63, soon)
        self.assertEqual(fake.call_args[0][0], weather.FORECAST_HOST)
        self.assertEqual(reading["source"], "forecast")

    def test_today_uses_forecast_not_archive(self):
        # The archive lags several days; today is not in it yet.
        today = datetime.now(timezone.utc).isoformat()
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()) as fake:
            weather.fetch_for_game(41.83, -87.63, today)
        self.assertEqual(fake.call_args[0][0], weather.FORECAST_HOST)


class TestFetchMany(unittest.TestCase):
    """Batching is a correctness concern, not just a speed one.

    Fetching a 15-game slate park-by-park is 15 requests against a
    rate-limited endpoint, and each retry multiplies wall-clock. Worse, a
    length mismatch between requested parks and returned payloads would
    silently align every reading to the wrong ballpark.
    """

    def test_single_request_for_many_parks(self):
        payloads = [hourly_payload(), hourly_payload(), hourly_payload()]
        with mock.patch.object(weather, "_get_json",
                               return_value=payloads) as fake:
            result = weather.fetch_many(
                [(41.9, -87.6), (39.9, -75.1), (42.3, -71.0)], "2025-07-09")
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(len(result), 3)

    def test_coordinates_are_comma_joined_in_order(self):
        with mock.patch.object(weather, "_get_json",
                               return_value=[hourly_payload()] * 2) as fake:
            weather.fetch_many([(41.9, -87.6), (39.9, -75.1)], "2025-07-09")
        params = fake.call_args[0][1]
        self.assertEqual(params["latitude"], "41.9,39.9")
        self.assertEqual(params["longitude"], "-87.6,-75.1")

    def test_single_location_object_response_is_wrapped(self):
        # One location returns an object, not a list.
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()):
            result = weather.fetch_many([(41.9, -87.6)], "2025-07-09")
        self.assertEqual(len(result), 1)

    def test_length_mismatch_raises_rather_than_misaligning(self):
        # Two parks requested, one payload returned. Zipping would silently
        # give park B's weather to nobody and park A's to the wrong game.
        with mock.patch.object(weather, "_get_json",
                               return_value=[hourly_payload()]):
            with self.assertRaises(WeatherError) as ctx:
                weather.fetch_many([(41.9, -87.6), (39.9, -75.1)], "2025-07-09")
        self.assertIn("refusing", str(ctx.exception))

    def test_empty_location_list_returns_empty_without_a_request(self):
        with mock.patch.object(weather, "_get_json") as fake:
            self.assertEqual(weather.fetch_many([], "2025-07-09"), [])
        fake.assert_not_called()

    def test_old_date_batches_against_the_archive(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat()
        with mock.patch.object(weather, "_get_json",
                               return_value=[hourly_payload()]) as fake:
            result = weather.fetch_many([(41.9, -87.6)], old)
        self.assertEqual(fake.call_args[0][0], weather.ARCHIVE_HOST)
        self.assertEqual(result[0]["_source"], "archive")

    def test_future_date_batches_against_the_forecast(self):
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        with mock.patch.object(weather, "_get_json",
                               return_value=[hourly_payload()]) as fake:
            result = weather.fetch_many([(41.9, -87.6)], soon)
        self.assertEqual(fake.call_args[0][0], weather.FORECAST_HOST)
        self.assertEqual(result[0]["_source"], "forecast")

    def test_invalid_coordinate_in_the_batch_is_rejected(self):
        with mock.patch.object(weather, "_get_json") as fake:
            with self.assertRaises(WeatherError):
                weather.fetch_many([(41.9, -87.6), (999.0, 0.0)], "2025-07-09")
        fake.assert_not_called()


class TestRequestParameters(unittest.TestCase):
    def test_requests_imperial_units(self):
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()) as fake:
            weather.fetch_forecast(41.83, -87.63, "2025-07-09")
        params = fake.call_args[0][1]
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(params["temperature_unit"], "fahrenheit")
        self.assertEqual(params["timezone"], "UTC")

    def test_requests_all_four_fields(self):
        with mock.patch.object(weather, "_get_json",
                               return_value=hourly_payload()) as fake:
            weather.fetch_forecast(41.83, -87.63, "2025-07-09")
        hourly = fake.call_args[0][1]["hourly"]
        for field in ("temperature_2m", "relative_humidity_2m",
                      "wind_speed_10m", "wind_direction_10m"):
            self.assertIn(field, hourly)


class TestValidation(unittest.TestCase):
    def test_out_of_range_coordinates_rejected(self):
        for lat, lon in ((91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)):
            with self.subTest(lat=lat, lon=lon):
                with self.assertRaises(WeatherError):
                    weather.fetch_forecast(lat, lon, "2025-07-09")

    def test_non_numeric_coordinates_rejected(self):
        with self.assertRaises(WeatherError):
            weather.fetch_forecast("41.83", -87.63, "2025-07-09")

    def test_bad_date_rejected(self):
        with self.assertRaises(WeatherError):
            weather.fetch_forecast(41.83, -87.63, "07/09/2025")

    def test_naive_timestamp_is_treated_as_utc(self):
        naive = weather._to_utc_datetime("2025-07-09T18:10:00")
        self.assertEqual(naive.tzinfo, timezone.utc)

    def test_z_suffix_is_parsed(self):
        parsed = weather._to_utc_datetime("2025-07-09T18:10:00Z")
        self.assertEqual(parsed.hour, 18)

    def test_unparseable_timestamp_rejected(self):
        with self.assertRaises(WeatherError):
            weather._to_utc_datetime("yesterday")


class TestTransportErrors(unittest.TestCase):
    """Open-Meteo rate-limits in practice -- a live 429 on the archive endpoint
    is what prompted the retry layer. A season backfill is thousands of
    requests, so this path is load-bearing, not defensive decoration."""

    @staticmethod
    def http_error(code):
        import urllib.error
        return urllib.error.HTTPError("u", code, "err", None, None)

    def test_rate_limit_is_retried_then_raises_a_distinct_error(self):
        slept = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=self.http_error(429)):
            with self.assertRaises(weather.WeatherRateLimited):
                weather._get_json(weather.ARCHIVE_HOST, {},
                                  sleep=slept.append)
        self.assertEqual(len(slept), weather.MAX_ATTEMPTS - 1)

    def test_backoff_grows_exponentially(self):
        slept = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=self.http_error(429)):
            with self.assertRaises(weather.WeatherRateLimited):
                weather._get_json(weather.ARCHIVE_HOST, {}, sleep=slept.append)
        self.assertEqual(slept, [2.0, 4.0, 8.0])

    def test_retry_succeeds_when_the_limit_clears(self):
        payload = json.dumps(hourly_payload()).encode()
        responses = [self.http_error(429), _FakeResponse(payload)]
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            result = weather._get_json(weather.ARCHIVE_HOST, {},
                                       sleep=lambda _: None)
        self.assertIn("hourly", result)

    def test_rate_limit_error_is_a_weather_error_subclass(self):
        # Callers catching WeatherError must still catch the rate-limit case.
        self.assertTrue(issubclass(weather.WeatherRateLimited, WeatherError))

    def test_non_retryable_status_fails_immediately(self):
        slept = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=self.http_error(404)):
            with self.assertRaises(WeatherError):
                weather._get_json(weather.FORECAST_HOST, {}, sleep=slept.append)
        self.assertEqual(slept, [])

    def test_network_failure_is_not_retried(self):
        import urllib.error
        slept = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(WeatherError):
                weather._get_json(weather.FORECAST_HOST, {}, sleep=slept.append)
        self.assertEqual(slept, [])


class _FakeResponse:
    """Minimal stand-in for a urlopen context manager."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


if __name__ == "__main__":
    unittest.main()
