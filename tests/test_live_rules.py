"""Tests for src.analysis.live_rules."""

import unittest
from src.analysis import live_rules


class TestMedianPrice(unittest.TestCase):
    """Test median_price calculation."""

    def test_median_price_single_book(self):
        """Single book price."""
        quotes = [{"book": "DK", "home_price": -110, "away_price": 110}]
        self.assertEqual(live_rules.median_price(quotes, "home"), -110)
        self.assertEqual(live_rules.median_price(quotes, "away"), 110)

    def test_median_price_three_books(self):
        """Three books: return middle value."""
        quotes = [
            {"book": "DK", "home_price": -110, "away_price": 110},
            {"book": "FD", "home_price": -100, "away_price": 100},
            {"book": "BR", "home_price": -120, "away_price": 120},
        ]
        # home: [-110, -100, -120] -> sorted [-120, -110, -100] -> median -110
        self.assertEqual(live_rules.median_price(quotes, "home"), -110)
        # away: [110, 100, 120] -> sorted [100, 110, 120] -> median 110
        self.assertEqual(live_rules.median_price(quotes, "away"), 110)

    def test_median_price_even_count(self):
        """Even count: use lower of the two middle values."""
        quotes = [
            {"book": "DK", "home_price": -110, "away_price": 110},
            {"book": "FD", "home_price": -100, "away_price": 100},
        ]
        # home: [-110, -100] -> sorted [-110, -100] -> lower middle -110
        self.assertEqual(live_rules.median_price(quotes, "home"), -110)

    def test_median_price_missing_side(self):
        """Side not in any quote returns None."""
        quotes = [{"book": "DK", "home_price": -110}]
        self.assertIsNone(live_rules.median_price(quotes, "away"))

    def test_median_price_empty_quotes(self):
        """Empty or None quotes returns None."""
        self.assertIsNone(live_rules.median_price([], "home"))
        self.assertIsNone(live_rules.median_price(None, "home"))

    def test_median_price_partial_quotes(self):
        """Some books don't have the side."""
        quotes = [
            {"book": "DK", "home_price": -110},
            {"book": "FD", "home_price": -100, "away_price": 100},
        ]
        # home: [-110, -100] -> sorted [-110, -100] -> lower middle -110
        self.assertEqual(live_rules.median_price(quotes, "home"), -110)
        # away: [100] -> median 100
        self.assertEqual(live_rules.median_price(quotes, "away"), 100)


class TestMLBFavoriteTrailsAfter3(unittest.TestCase):
    """Test mlb_favorite_trails_after_3 rule."""

    def test_fires_favorite_trailing_by_1_run(self):
        """Fires when favourite trails by 1 run at end of 3rd."""
        pregame = {
            "game_id": "mlb_123",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "half": "top",
            "outs": 0,
            "home_runs": 2,
            "away_runs": 3,
            "observed_utc": "2026-09-14T20:00:00Z",
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [
                {"book": "DK", "home_price": -110, "away_price": 110},
            ]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["rule_id"], "mlb_favorite_trails_after_3")
        self.assertEqual(candidate["side"], "home")
        self.assertEqual(candidate["price"], -110)
        self.assertEqual(candidate["trigger"]["margin"], -1)

    def test_fires_favorite_trailing_by_2_runs(self):
        """Fires when favourite trails by 2 runs."""
        pregame = {
            "game_id": "mlb_124",
            "sport": "mlb",
            "favorite": "away",
            "favorite_prob": 0.55,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "home_runs": 5,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": 110, "away_price": -110}]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["side"], "away")
        self.assertEqual(candidate["trigger"]["margin"], -2)

    def test_silent_when_favorite_leads(self):
        """Silent when favourite is leading."""
        pregame = {
            "game_id": "mlb_125",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "home_runs": 4,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_trailing_by_3_runs(self):
        """Silent when trailing by more than 2 runs."""
        pregame = {
            "game_id": "mlb_126",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "home_runs": 1,
            "away_runs": 4,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_before_inning_3_ends(self):
        """Silent before 3rd inning ends."""
        pregame = {
            "game_id": "mlb_127",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "Middle",  # Still in progress
            "home_runs": 2,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_favorite_prob_below_threshold(self):
        """Silent when favorite_prob < 0.55."""
        pregame = {
            "game_id": "mlb_128",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.54,  # Below 0.55
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "home_runs": 2,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_no_quote(self):
        """Silent when favourite side not quoted."""
        pregame = {
            "game_id": "mlb_129",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
        }
        state = {
            "inning": 3,
            "inning_state": "End",
            "home_runs": 2,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "away_price": 110}]  # home_price missing
        }

        candidate = live_rules.evaluate("mlb_favorite_trails_after_3",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)


class TestMLBStarterPulledEarly(unittest.TestCase):
    """Test mlb_starter_pulled_early rule."""

    def test_fires_when_starter_pulled_early(self):
        """Fires when starter pulled before 4 innings, favourite leads."""
        pregame = {
            "game_id": "mlb_201",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "pitcher_1", "away": "pitcher_2"},
        }
        state = {
            "inning": 2,
            "half": "top",  # Favourite (home) is on defence
            "pitcher_id": "pitcher_relief",  # Different pitcher
            "home_runs": 3,
            "away_runs": 1,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_starter_pulled_early",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["rule_id"], "mlb_starter_pulled_early")
        self.assertEqual(candidate["side"], "away")  # Opponent side

    def test_silent_when_tied(self):
        """Fires when tied."""
        pregame = {
            "game_id": "mlb_202",
            "sport": "mlb",
            "favorite": "away",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "pitcher_1", "away": "pitcher_2"},
        }
        state = {
            "inning": 3,
            "half": "bottom",  # Favourite (away) is on defence
            "pitcher_id": "pitcher_relief",
            "home_runs": 2,
            "away_runs": 2,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": 110, "away_price": -110}]
        }

        candidate = live_rules.evaluate("mlb_starter_pulled_early",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)  # Should fire (tied)

    def test_silent_when_favourite_trailing(self):
        """Silent when favourite is trailing."""
        pregame = {
            "game_id": "mlb_203",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "pitcher_1", "away": "pitcher_2"},
        }
        state = {
            "inning": 2,
            "half": "top",
            "pitcher_id": "pitcher_relief",
            "home_runs": 1,
            "away_runs": 3,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_starter_pulled_early",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_inning_5(self):
        """Silent when inning > 4."""
        pregame = {
            "game_id": "mlb_204",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "pitcher_1", "away": "pitcher_2"},
        }
        state = {
            "inning": 5,
            "half": "top",
            "pitcher_id": "pitcher_relief",
            "home_runs": 3,
            "away_runs": 1,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_starter_pulled_early",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_starter_still_in(self):
        """Silent when starter hasn't changed."""
        pregame = {
            "game_id": "mlb_205",
            "sport": "mlb",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "pitcher_1", "away": "pitcher_2"},
        }
        state = {
            "inning": 2,
            "half": "top",
            "pitcher_id": "pitcher_1",  # Same starter
            "home_runs": 3,
            "away_runs": 1,
        }
        quote = {
            "observed_utc": "2026-09-14T20:00:00Z",
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("mlb_starter_pulled_early",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)


class TestNFLFavoriteTrailsHalftime(unittest.TestCase):
    """Test nfl_favorite_trails_halftime rule."""

    def test_fires_at_90_minutes(self):
        """Fires at 90 minutes (middle of halftime window)."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=90)

        pregame = {
            "game_id": "nfl_101",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 10,
            "away_score": 14,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["rule_id"], "nfl_favorite_trails_halftime")
        self.assertEqual(candidate["trigger"]["margin"], -4)

    def test_silent_at_79_minutes(self):
        """Silent at 79 minutes (before halftime window)."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=79)

        pregame = {
            "game_id": "nfl_102",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 10,
            "away_score": 14,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_at_101_minutes(self):
        """Silent at 101 minutes (after halftime window)."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=101)

        pregame = {
            "game_id": "nfl_103",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 10,
            "away_score": 14,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_favourite_leads(self):
        """Silent when favourite is leading."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=90)

        pregame = {
            "game_id": "nfl_104",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 17,
            "away_score": 14,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_trailing_by_8_points(self):
        """Silent when trailing by more than 7 points."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=90)

        pregame = {
            "game_id": "nfl_105",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 7,
            "away_score": 15,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)

    def test_silent_when_favourite_prob_below_threshold(self):
        """Silent when favorite_prob < 0.60."""
        from datetime import datetime, timezone, timedelta

        commence = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        observed = commence + timedelta(minutes=90)

        pregame = {
            "game_id": "nfl_106",
            "sport": "nfl",
            "favorite": "home",
            "favorite_prob": 0.59,  # Below 0.60
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": commence.isoformat(),
        }
        state = {
            "home_score": 10,
            "away_score": 14,
            "completed": False,
            "observed_utc": observed.isoformat(),
        }
        quote = {
            "observed_utc": observed.isoformat(),
            "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]
        }

        candidate = live_rules.evaluate("nfl_favorite_trails_halftime",
                                       pregame=pregame, state=state, quote=quote)
        self.assertIsNone(candidate)


class TestEvaluateAll(unittest.TestCase):
    """Test evaluate_all dispatcher."""

    def test_mlb_returns_mlb_rules(self):
        """evaluate_all for MLB returns only MLB rules."""
        pregame = {
            "sport": "mlb",
            "game_id": "mlb_501",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "starter_ids": {"home": "p1", "away": "p2"},
        }
        state = {
            "inning": 1,
            "inning_state": "Start",
            "half": "top",
            "outs": 0,
            "home_runs": 0,
            "away_runs": 0,
            "pitcher_id": "p1",
        }
        quote = None

        candidates = live_rules.evaluate_all(pregame=pregame, state=state, quote=quote)
        # No rules should fire with this state
        self.assertEqual(len(candidates), 0)

    def test_nfl_returns_nfl_rules(self):
        """evaluate_all for NFL returns only NFL rules."""
        pregame = {
            "sport": "nfl",
            "game_id": "nfl_501",
            "favorite": "home",
            "favorite_prob": 0.60,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "kickoff_utc": "2026-09-14T20:00:00Z",
        }
        state = {
            "home_score": 0,
            "away_score": 0,
            "completed": False,
        }
        quote = None

        candidates = live_rules.evaluate_all(pregame=pregame, state=state, quote=quote)
        # No rules should fire with this state
        self.assertEqual(len(candidates), 0)


class TestFirstDefensivePitcher(unittest.TestCase):
    """D12: the pitcher first observed on the favourite's defence, the value
    _mlb_starter_pulled_early's docstring requires a caller to feed into
    starter_ids -- not the pregame probable pitcher."""

    def test_returns_first_pitcher_id_on_favorites_defensive_half(self):
        """Home favourite is on defence in the top half; the first top-half
        row with a pitcher_id wins, even if earlier bottom-half rows (the
        favourite batting) named a different pitcher_id."""
        state_rows = [
            {"half": "bottom", "pitcher_id": "opp_starter"},  # favourite batting
            {"half": "top", "pitcher_id": None},               # not recorded yet
            {"half": "top", "pitcher_id": "real_starter"},
            {"half": "top", "pitcher_id": "reliever"},         # later, irrelevant
        ]
        self.assertEqual(
            live_rules.first_defensive_pitcher(state_rows, "home"),
            "real_starter")

    def test_away_favorite_uses_bottom_half(self):
        state_rows = [
            {"half": "top", "pitcher_id": "opp_starter"},
            {"half": "bottom", "pitcher_id": "real_starter"},
        ]
        self.assertEqual(
            live_rules.first_defensive_pitcher(state_rows, "away"),
            "real_starter")

    def test_no_defensive_row_yet_returns_none(self):
        state_rows = [{"half": "bottom", "pitcher_id": "opp_starter"}]
        self.assertIsNone(live_rules.first_defensive_pitcher(state_rows, "home"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(live_rules.first_defensive_pitcher([], "home"))
        self.assertIsNone(live_rules.first_defensive_pitcher(None, "away"))

    def test_rule_fires_against_the_observed_starter_not_the_probable(self):
        """D12 end to end: the pregame probable pitcher was scratched: the
        real starter (found by first_defensive_pitcher over the game's own
        state history) is who the rule must compare the current pitcher
        against. Comparing against the stale probable would fire this rule
        on the very first batter, which is exactly the bug D12 records."""
        probable_pitcher = "probable_scratched"
        state_rows = [
            {"half": "top", "pitcher_id": "actual_starter", "inning": 1},
            {"half": "top", "pitcher_id": "actual_starter", "inning": 2},
        ]
        confirmed_starter = live_rules.first_defensive_pitcher(state_rows, "home")
        self.assertEqual(confirmed_starter, "actual_starter")
        self.assertNotEqual(confirmed_starter, probable_pitcher)

        pregame = {
            "game_id": "mlb_d12", "sport": "mlb", "favorite": "home",
            "favorite_prob": 0.60, "home_team": "Yankees", "away_team": "Red Sox",
            # Seeded with the CONFIRMED starter, per the docstring contract --
            # not the probable pitcher that never actually started.
            "starter_ids": {"home": confirmed_starter, "away": "away_p"},
        }
        # The actual starter is still in: no pitcher change yet, so the rule
        # must NOT fire, even though it would have if compared against the
        # stale probable (which never matches "actual_starter" either, and
        # would have fired immediately on a false "pitcher changed" read).
        state = {"inning": 2, "half": "top", "pitcher_id": "actual_starter",
                 "home_runs": 1, "away_runs": 0}
        quote = {"observed_utc": "2026-09-15T20:00:00Z",
                 "quotes": [{"book": "DK", "home_price": -110, "away_price": 110}]}
        self.assertIsNone(live_rules.evaluate(
            "mlb_starter_pulled_early", pregame=pregame, state=state, quote=quote))

        # The actual starter is pulled for a reliever: now it must fire.
        state["pitcher_id"] = "actual_reliever"
        candidate = live_rules.evaluate(
            "mlb_starter_pulled_early", pregame=pregame, state=state, quote=quote)
        self.assertIsNotNone(candidate)


if __name__ == "__main__":
    unittest.main()
