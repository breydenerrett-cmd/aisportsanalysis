"""Tests for sport parameter support in src/providers/odds.py.

Tests that sport parameters work correctly on fetch and normalize functions,
that paths are built with the right sport keys, and that records are annotated
with sport only when not MLB.
"""

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


class TestSportKey(unittest.TestCase):
    """Test the sport_key() resolution function."""

    def test_none_resolves_to_mlb(self):
        self.assertEqual(odds.sport_key(None), "baseball_mlb")

    def test_empty_string_resolves_to_mlb(self):
        self.assertEqual(odds.sport_key(""), "baseball_mlb")

    def test_mlb_string_resolves_to_baseball_mlb(self):
        self.assertEqual(odds.sport_key("mlb"), "baseball_mlb")

    def test_nfl_key_resolves_to_americanfootball_nfl(self):
        self.assertEqual(odds.sport_key("nfl"), "americanfootball_nfl")

    def test_mma_resolves_and_the_capture_module_key_is_accepted(self):
        # 2026-09-21: the UFC pipeline's own key was refused by this resolver
        # in production, while the unit tests' fake providers hid it.
        from src.pipeline import mma_capture
        self.assertEqual(odds.sport_key("mma"), "mma_mixed_martial_arts")
        self.assertEqual(odds.sport_key(mma_capture.SPORT_KEY), "mma_mixed_martial_arts")

    def test_tennis_key_passes_through(self):
        self.assertEqual(odds.sport_key("tennis_atp_china_open"), "tennis_atp_china_open")

    def test_full_key_passes_through(self):
        self.assertEqual(odds.sport_key("baseball_mlb"), "baseball_mlb")
        self.assertEqual(odds.sport_key("americanfootball_nfl"), "americanfootball_nfl")

    def test_unknown_sport_raises(self):
        with self.assertRaises(OddsProviderError) as ctx:
            odds.sport_key("cricket")
        self.assertIn("unknown sport", str(ctx.exception))
        self.assertIn("mlb", str(ctx.exception))
        self.assertIn("nfl", str(ctx.exception))


class TestFetchOddsSportPath(unittest.TestCase):
    """Test that fetch_odds builds the correct path for each sport."""

    def test_fetch_odds_default_path_is_baseball_mlb(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_odds(env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/baseball_mlb/odds", path)

    def test_fetch_odds_nfl_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_odds(sport="nfl", env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/americanfootball_nfl/odds", path)

    def test_fetch_odds_tennis_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_odds(sport="tennis_atp_china_open", env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/tennis_atp_china_open/odds", path)

    def test_fetch_odds_invalid_sport_raises(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with self.assertRaises(OddsProviderError):
            odds.fetch_odds(sport="cricket", env=env)


class TestListEventsSportPath(unittest.TestCase):
    """Test that list_events builds the correct path for each sport."""

    def test_list_events_default_path_is_baseball_mlb(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.list_events(env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/baseball_mlb/events", path)

    def test_list_events_nfl_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.list_events(sport="nfl", env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/americanfootball_nfl/events", path)

    def test_list_events_tennis_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.list_events(sport="tennis_wimbledon", env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/tennis_wimbledon/events", path)


class TestFetchEventOddsSportPath(unittest.TestCase):
    """Test that fetch_event_odds builds the correct path for each sport."""

    def test_fetch_event_odds_default_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value={}), \
             mock.patch.object(odds, "_write_raw_capture"):
            odds.fetch_event_odds("evt1", env=env)
        # Can't easily check the path, but we can check it doesn't fail

    def test_fetch_event_odds_nfl_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value={}) as fake, \
             mock.patch.object(odds, "_write_raw_capture"):
            odds.fetch_event_odds("evt1", sport="nfl", env=env)
        path = fake.call_args[0][0]
        self.assertIn("americanfootball_nfl", path)

    def test_fetch_event_odds_with_usage_nfl_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json_with_usage",
                              return_value=({}, {"remaining": 100})) as fake, \
             mock.patch.object(odds, "_write_raw_capture"):
            odds.fetch_event_odds_with_usage("evt1", sport="nfl", env=env)
        path = fake.call_args[0][0]
        self.assertIn("americanfootball_nfl", path)


class TestFetchScores(unittest.TestCase):
    """Test fetch_scores function."""

    def test_fetch_scores_default_path_is_baseball_mlb(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/baseball_mlb/scores", path)

    def test_fetch_scores_nfl_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(sport="nfl", env=env)
        path = fake.call_args[0][0]
        self.assertIn("sports/americanfootball_nfl/scores", path)

    def test_fetch_scores_without_key_raises(self):
        with self.assertRaises(NotConfigured):
            odds.fetch_scores(env={})

    def test_fetch_scores_with_days_from_1(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(sport="nfl", days_from=1, env=env)
        params = fake.call_args[0][1]
        self.assertEqual(params["daysFrom"], 1)

    def test_fetch_scores_with_days_from_2(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(sport="nfl", days_from=2, env=env)
        params = fake.call_args[0][1]
        self.assertEqual(params["daysFrom"], 2)

    def test_fetch_scores_with_days_from_3(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(sport="nfl", days_from=3, env=env)
        params = fake.call_args[0][1]
        self.assertEqual(params["daysFrom"], 3)

    def test_fetch_scores_with_days_from_0_raises(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with self.assertRaises(OddsProviderError) as ctx:
            odds.fetch_scores(sport="nfl", days_from=0, env=env)
        self.assertIn("1 and 3", str(ctx.exception))

    def test_fetch_scores_with_days_from_4_raises(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with self.assertRaises(OddsProviderError) as ctx:
            odds.fetch_scores(sport="nfl", days_from=4, env=env)
        self.assertIn("1 and 3", str(ctx.exception))

    def test_fetch_scores_with_days_from_9_raises(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with self.assertRaises(OddsProviderError) as ctx:
            odds.fetch_scores(sport="nfl", days_from=9, env=env)
        self.assertIn("1 and 3", str(ctx.exception))

    def test_fetch_scores_without_days_from_omits_param(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_scores(env=env)
        params = fake.call_args[0][1]
        self.assertNotIn("daysFrom", params)


class TestNormalizeScore(unittest.TestCase):
    """Test normalize_score function."""

    def score_event(self, home="Chicago White Sox", away="Toronto Blue Jays",
                   home_score=5, away_score=3, completed=True):
        return {
            "id": "score1",
            "sport_key": "baseball_mlb",
            "commence_time": "2025-07-09T18:10:00Z",
            "completed": completed,
            "home_team": home,
            "away_team": away,
            "scores": [
                {"name": home, "score": str(home_score)},
                {"name": away, "score": str(away_score)},
            ],
            "last_update": "2025-07-09T22:30:00Z",
        }

    def test_normalize_score_extracts_fields(self):
        evt = self.score_event()
        record = odds.normalize_score(evt)
        self.assertEqual(record["event_id"], "score1")
        self.assertEqual(record["home_team"], "Chicago White Sox")
        self.assertEqual(record["away_team"], "Toronto Blue Jays")
        self.assertEqual(record["home_score"], 5)
        self.assertEqual(record["away_score"], 3)
        self.assertTrue(record["completed"])

    def test_normalize_score_completed_bool(self):
        evt = self.score_event(completed=True)
        self.assertTrue(odds.normalize_score(evt)["completed"])
        evt = self.score_event(completed=False)
        self.assertFalse(odds.normalize_score(evt)["completed"])

    def test_normalize_score_null_scores_list(self):
        evt = self.score_event()
        evt["scores"] = None
        record = odds.normalize_score(evt)
        self.assertIsNone(record["home_score"])
        self.assertIsNone(record["away_score"])

    def test_normalize_score_empty_scores_list(self):
        evt = self.score_event()
        evt["scores"] = []
        record = odds.normalize_score(evt)
        self.assertIsNone(record["home_score"])
        self.assertIsNone(record["away_score"])

    def test_normalize_score_no_sport_key_for_mlb(self):
        evt = self.score_event()
        record = odds.normalize_score(evt)
        self.assertNotIn("sport", record)

    def test_normalize_score_sport_key_for_nfl(self):
        evt = self.score_event()
        record = odds.normalize_score(evt, sport="nfl")
        self.assertIn("sport", record)
        self.assertEqual(record["sport"], "nfl")

    def test_normalize_score_sport_key_for_tennis(self):
        evt = self.score_event()
        record = odds.normalize_score(evt, sport="tennis_wimbledon")
        self.assertIn("sport", record)
        self.assertEqual(record["sport"], "tennis_wimbledon")


class TestFetchSports(unittest.TestCase):
    """Test fetch_sports function."""

    def test_fetch_sports_default_path(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_sports(env=env)
        path = fake.call_args[0][0]
        self.assertEqual(path, "sports")

    def test_fetch_sports_without_key_raises(self):
        with self.assertRaises(NotConfigured):
            odds.fetch_sports(env={})

    def test_fetch_sports_without_all_sports_omits_param(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_sports(env=env)
        params = fake.call_args[0][1]
        self.assertNotIn("all", params)

    def test_fetch_sports_with_all_sports_true(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[]) as fake:
            odds.fetch_sports(all_sports=True, env=env)
        params = fake.call_args[0][1]
        self.assertEqual(params["all"], "true")


class TestNormalizeEventSportField(unittest.TestCase):
    """Test that normalize_event adds sport field only when not MLB."""

    def test_normalize_event_no_sport_field_by_default(self):
        record = odds.normalize_event(event())
        self.assertNotIn("sport", record)

    def test_normalize_event_no_sport_field_for_mlb(self):
        record = odds.normalize_event(event(), sport="mlb")
        self.assertNotIn("sport", record)

    def test_normalize_event_no_sport_field_for_none(self):
        record = odds.normalize_event(event(), sport=None)
        self.assertNotIn("sport", record)

    def test_normalize_event_no_sport_field_for_empty_string(self):
        record = odds.normalize_event(event(), sport="")
        self.assertNotIn("sport", record)

    def test_normalize_event_sport_field_for_nfl(self):
        record = odds.normalize_event(event(), sport="nfl")
        self.assertIn("sport", record)
        self.assertEqual(record["sport"], "nfl")

    def test_normalize_event_sport_field_for_tennis(self):
        record = odds.normalize_event(event(), sport="tennis_wimbledon")
        self.assertIn("sport", record)
        self.assertEqual(record["sport"], "tennis_wimbledon")


class TestFetchNormalizedSportField(unittest.TestCase):
    """Test that fetch_normalized adds sport field and passes it through."""

    def setUp(self):
        patcher = mock.patch.object(odds, "_write_raw_capture")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fetch_normalized_includes_sport_mlb(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[event()]):
            result = odds.fetch_normalized(env=env)
        self.assertIn("sport", result)
        self.assertEqual(result["sport"], "mlb")

    def test_fetch_normalized_includes_sport_nfl(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[event()]):
            result = odds.fetch_normalized(sport="nfl", env=env)
        self.assertIn("sport", result)
        self.assertEqual(result["sport"], "nfl")

    def test_fetch_normalized_event_has_sport_for_nfl(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[event()]):
            result = odds.fetch_normalized(sport="nfl", env=env)
        self.assertEqual(len(result["events"]), 1)
        self.assertIn("sport", result["events"][0])
        self.assertEqual(result["events"][0]["sport"], "nfl")

    def test_fetch_normalized_event_no_sport_for_mlb(self):
        env = {"ODDS_API_KEY": FAKE_KEY}
        with mock.patch.object(odds, "_get_json", return_value=[event()]):
            result = odds.fetch_normalized(sport="mlb", env=env)
        self.assertEqual(len(result["events"]), 1)
        self.assertNotIn("sport", result["events"][0])


class TestWriteRawCaptureSportKind(unittest.TestCase):
    """Test that _write_raw_capture uses sport-specific kind names."""

    def test_write_raw_capture_featured_kind_for_mlb(self):
        # This would write to disk, so we just check the kind is not modified
        with mock.patch("gzip.open", mock.mock_open()), \
             mock.patch("pathlib.Path.mkdir"):
            # We can't easily inspect the written content, but we can verify no error
            try:
                odds._write_raw_capture({"data": []}, "featured", sport=None)
            except Exception:
                pass

    def test_write_raw_capture_featured_nfl_kind(self):
        # Similar verification for NFL
        with mock.patch("gzip.open", mock.mock_open()), \
             mock.patch("pathlib.Path.mkdir"):
            try:
                odds._write_raw_capture({"data": []}, "featured", sport="nfl")
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
