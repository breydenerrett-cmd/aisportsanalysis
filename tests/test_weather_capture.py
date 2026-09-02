"""Tests for src/pipeline/weather_capture.py. Hermetic: fake MLB and weather
fetchers are injected; no network call is ever made, and every write goes to
a tempfile store."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.data import parks
from src.pipeline import weather_capture
from src.providers import weather as weather_provider

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


def _game(game_pk, home_team, hours_to_first_pitch, away_team="SF",
          venue="Some Park", game_date="2026-09-02"):
    start = NOW + dt.timedelta(hours=hours_to_first_pitch)
    return {
        "game_pk": game_pk,
        "date": game_date,
        "start_time_utc": start.isoformat().replace("+00:00", "Z"),
        "home_team": home_team,
        "away_team": away_team,
        "venue": venue,
    }


def _hourly_payload(hours=None):
    hours = hours or ["2026-09-02T17:00", "2026-09-02T18:00", "2026-09-02T19:00"]
    return {
        "hourly": {
            "time": hours,
            "temperature_2m": [70.0, 72.0, 74.0],
            "relative_humidity_2m": [55, 58, 60],
            "wind_speed_10m": [5.0, 6.0, 7.0],
            "wind_direction_10m": [190, 200, 210],
            "precipitation_probability": [10, 20, 30],
            "surface_pressure": [1012.0, 1011.5, 1011.0],
        }
    }


class FakeMLB:
    """A fixed schedule per date, keyed by ISO date string."""

    def __init__(self, by_date):
        self.by_date = by_date
        self.calls = []

    def fetch_games(self, game_date, timeout=None):
        self.calls.append(game_date)
        if game_date in self.by_date and isinstance(self.by_date[game_date], Exception):
            raise self.by_date[game_date]
        return self.by_date.get(game_date, [])


class FakeWeather:
    """Fakes only the network call; `extract_hour` is the real parser, so a
    test exercises real payload-parsing logic against a canned response."""

    WeatherError = weather_provider.WeatherError
    extract_hour = staticmethod(weather_provider.extract_hour)

    def __init__(self, payload=None, fail_for=None):
        self.payload = payload if payload is not None else _hourly_payload()
        self.fail_for = fail_for or set()  # set of (lat, lon) to fail on
        self.calls = []

    def fetch_forecast(self, lat, lon, game_date, timeout=15,
                       extra_hourly_fields=None):
        self.calls.append((lat, lon, game_date, tuple(extra_hourly_fields or ())))
        if (lat, lon) in self.fail_for:
            raise self.WeatherError("open-meteo unreachable")
        return self.payload


class BasicCaptureTests(unittest.TestCase):
    def test_one_row_per_game_with_the_documented_fields(self):
        games = {"2026-09-02": [_game(1, "ATL", 6)], "2026-09-03": []}
        mlb = FakeMLB(games)
        weather = FakeWeather()
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store, mlb=mlb,
                                         weather=weather)
            rows = weather_capture.read(store)
        self.assertEqual(report["games"], 1)
        self.assertEqual(report["rows"], 1)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for field in ("observed_utc", "game_pk", "game_date", "park", "venue",
                      "commence_time", "hours_to_first_pitch", "roof",
                      "temp_f", "humidity_pct", "wind_mph", "wind_from_deg",
                      "precip_probability_pct", "pressure_hpa", "source",
                      "provider_run_time"):
            self.assertIn(field, row)
        self.assertEqual(row["game_pk"], 1)
        self.assertEqual(row["park"], "ATL")
        self.assertEqual(row["source"], "forecast")
        self.assertAlmostEqual(row["hours_to_first_pitch"], 6.0, places=2)

    def test_both_todays_and_tomorrows_schedule_are_asked_for(self):
        mlb = FakeMLB({"2026-09-02": [], "2026-09-03": []})
        weather_capture.run(now=NOW, store=Path(tempfile.mkdtemp()) / "w.jsonl",
                            mlb=mlb, weather=FakeWeather())
        self.assertEqual(set(mlb.calls), {"2026-09-02", "2026-09-03"})

    def test_a_roofed_park_is_still_recorded_with_its_roof_marked(self):
        games = {"2026-09-02": [_game(2, "TOR", 4)], "2026-09-03": []}
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            weather_capture.run(now=NOW, store=store, mlb=FakeMLB(games),
                               weather=FakeWeather())
            row = weather_capture.read(store)[0]
        self.assertEqual(row["roof"], parks.get_park("TOR")["roof"])
        self.assertNotEqual(row["roof"], "open")

    def test_the_forecast_call_asks_for_the_extra_hourly_fields(self):
        games = {"2026-09-02": [_game(3, "BOS", 2)], "2026-09-03": []}
        weather = FakeWeather()
        weather_capture.run(now=NOW, store=Path(tempfile.mkdtemp()) / "w.jsonl",
                            mlb=FakeMLB(games), weather=weather)
        self.assertEqual(len(weather.calls), 1)
        _, _, _, extra_fields = weather.calls[0]
        self.assertEqual(set(extra_fields), set(weather_capture.EXTRA_HOURLY_FIELDS))

    def test_no_games_writes_no_rows_and_no_error(self):
        mlb = FakeMLB({"2026-09-02": [], "2026-09-03": []})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store, mlb=mlb,
                                         weather=FakeWeather())
        self.assertEqual(report["rows"], 0)
        self.assertEqual(report["errors"], [])
        self.assertFalse(store.exists())


class FailureIsHonestTests(unittest.TestCase):
    """A provider fault is a skip line, never a crash, and never silent."""

    def test_a_schedule_outage_is_recorded_and_does_not_crash(self):
        mlb = FakeMLB({"2026-09-02": RuntimeError("MLB API down"),
                       "2026-09-03": []})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store, mlb=mlb,
                                         weather=FakeWeather())
        self.assertEqual(report["rows"], 0)
        self.assertTrue(any("schedule 2026-09-02" in e for e in report["errors"]))

    def test_one_bad_park_does_not_cost_the_rest_of_the_slate(self):
        atl_lat_lon = (parks.get_park("ATL")["lat"], parks.get_park("ATL")["lon"])
        games = {"2026-09-02": [_game(1, "ATL", 6), _game(2, "BOS", 5)],
                 "2026-09-03": []}
        weather = FakeWeather(fail_for={atl_lat_lon})
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store,
                                         mlb=FakeMLB(games), weather=weather)
            rows = weather_capture.read(store)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_pk"], 2)
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn("game 1", report["errors"][0])

    def test_an_unknown_team_abbreviation_is_a_skip_not_a_crash(self):
        games = {"2026-09-02": [_game(9, "ZZZ", 3)], "2026-09-03": []}
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store,
                                         mlb=FakeMLB(games), weather=FakeWeather())
        self.assertEqual(report["rows"], 0)
        self.assertTrue(any("game 9" in e for e in report["errors"]))

    def test_a_game_missing_a_start_time_is_skipped_silently(self):
        # Nothing to key a row on; this is not a provider failure.
        game = _game(4, "SD", 3)
        game["start_time_utc"] = None
        games = {"2026-09-02": [game], "2026-09-03": []}
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            report = weather_capture.run(now=NOW, store=store,
                                         mlb=FakeMLB(games), weather=FakeWeather())
        self.assertEqual(report["rows"], 0)
        self.assertEqual(report["errors"], [])


class AppendOnlyTests(unittest.TestCase):
    def test_two_ticks_append_rather_than_overwrite(self):
        games = {"2026-09-02": [_game(1, "ATL", 6)], "2026-09-03": []}
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            weather_capture.run(now=NOW, store=store, mlb=FakeMLB(games),
                               weather=FakeWeather())
            weather_capture.run(now=NOW + dt.timedelta(hours=1), store=store,
                               mlb=FakeMLB(games), weather=FakeWeather())
            rows = weather_capture.read(store)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["observed_utc"], rows[1]["observed_utc"])

    def test_one_tick_writes_at_most_one_row_per_game(self):
        # Idempotent within a tick: each game is looked up once even though
        # it could in principle appear on both the today and tomorrow pulls
        # if a caller's date arithmetic ever overlapped.
        games = {"2026-09-02": [_game(1, "ATL", 6)], "2026-09-03": []}
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            weather_capture.run(now=NOW, store=store, mlb=FakeMLB(games),
                               weather=FakeWeather())
            rows = weather_capture.read(store)
        self.assertEqual(len({r["game_pk"] for r in rows}), 1)

    def test_an_interrupted_append_does_not_corrupt_the_next_row(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "weather.jsonl"
            store.write_text('{"observed_utc":"a","game_pk":1}\n'
                             '{"observed_utc":"b","game_p', encoding="utf-8")
            weather_capture.append([{"observed_utc": "c", "game_pk": 3}], store)
            lines = store.read_text(encoding="utf-8").splitlines()
            rows = weather_capture.read(store)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
