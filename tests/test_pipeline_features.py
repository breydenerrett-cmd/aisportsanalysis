"""Tests for src/pipeline/features.py.

The centrepiece is TestNoLookahead. Lookahead bias is the most expensive silent failure
in this project -- a leaked model backtests beautifully and loses money live -- so it is
proven here rather than trusted, by injecting future games with absurd values and
asserting the output does not move by a single byte.
"""

import unittest

from src.pipeline import features
from src.pipeline.features import FeatureError


def game(pk, day, away, home, away_score, home_score):
    winner = home if home_score > away_score else (away if away_score > home_score else None)
    return {
        "game_pk": pk, "date": day, "game_type": "R",
        "away_team": away, "home_team": home,
        "away_score": away_score, "home_score": home_score,
        "winner": winner,
        "home_won": (1 if home_score > away_score else 0) if winner else None,
        "total_runs": away_score + home_score,
        "run_differential": abs(home_score - away_score),
    }


def store_from(games):
    return {str(g["game_pk"]): g for g in games}


def season(team_a="AAA", team_b="BBB", days=20, start_day=1, a_wins=True):
    """A simple alternating schedule so counts are easy to reason about."""
    games = []
    for i in range(days):
        day = f"2025-05-{start_day + i:02d}"
        if a_wins:
            games.append(game(100 + i, day, team_a, team_b, 5, 2))
        else:
            games.append(game(100 + i, day, team_a, team_b, 2, 5))
    return games


class TestGamesBefore(unittest.TestCase):
    def test_excludes_the_cutoff_date_itself(self):
        # At prediction time, that day's games have not been played.
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1),
                            game(2, "2025-05-02", "AAA", "BBB", 3, 1)])
        before = features.games_before(store, "2025-05-02")
        self.assertEqual([g["game_pk"] for g in before], [1])

    def test_excludes_future_games(self):
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1),
                            game(2, "2025-06-01", "AAA", "BBB", 3, 1)])
        self.assertEqual(len(features.games_before(store, "2025-05-15")), 1)

    def test_returns_oldest_first(self):
        store = store_from([game(2, "2025-05-05", "AAA", "BBB", 3, 1),
                            game(1, "2025-05-01", "AAA", "BBB", 3, 1)])
        before = features.games_before(store, "2025-06-01")
        self.assertEqual([g["game_pk"] for g in before], [1, 2])

    def test_team_filter_matches_home_or_away(self):
        store = store_from([
            game(1, "2025-05-01", "AAA", "BBB", 3, 1),
            game(2, "2025-05-02", "CCC", "AAA", 3, 1),
            game(3, "2025-05-03", "CCC", "DDD", 3, 1),
        ])
        pks = [g["game_pk"] for g in features.games_before(store, "2025-06-01", team="AAA")]
        self.assertEqual(pks, [1, 2])

    def test_rows_with_no_date_are_skipped_not_crashed_on(self):
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1)])
        store["2"] = {"game_pk": 2, "date": None, "away_team": "AAA",
                      "home_team": "BBB"}
        self.assertEqual(len(features.games_before(store, "2025-06-01")), 1)

    def test_unparseable_date_is_skipped(self):
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1)])
        store["2"] = {"game_pk": 2, "date": "not-a-date", "away_team": "AAA",
                      "home_team": "BBB"}
        self.assertEqual(len(features.games_before(store, "2025-06-01")), 1)


class TestNoLookahead(unittest.TestCase):
    """The property that matters most. Proven, not assumed.

    Each test injects games AFTER the cutoff with values extreme enough that any leak
    would be unmistakable, then asserts the features are identical.
    """

    def build(self, extra=()):
        base = season(days=20)
        return store_from(list(base) + list(extra))

    def test_a_future_blowout_does_not_change_any_feature(self):
        cutoff = "2025-05-15"
        clean = features.team_features(self.build(), "AAA", cutoff)
        poisoned = features.team_features(
            self.build([game(999, "2025-05-16", "AAA", "BBB", 99, 0),
                        game(998, "2025-09-01", "AAA", "BBB", 99, 0)]),
            "AAA", cutoff,
        )
        self.assertEqual(clean, poisoned)

    def test_a_future_losing_streak_does_not_change_any_feature(self):
        cutoff = "2025-05-15"
        future_losses = [game(900 + i, f"2025-06-{i + 1:02d}", "AAA", "BBB", 0, 20)
                         for i in range(10)]
        self.assertEqual(
            features.team_features(self.build(), "AAA", cutoff),
            features.team_features(self.build(future_losses), "AAA", cutoff),
        )

    def test_a_game_on_the_cutoff_date_does_not_leak(self):
        # The off-by-one that would be easiest to get wrong.
        cutoff = "2025-05-15"
        same_day = [game(950, cutoff, "AAA", "BBB", 50, 0)]
        self.assertEqual(
            features.team_features(self.build(), "AAA", cutoff),
            features.team_features(self.build(same_day), "AAA", cutoff),
        )

    def test_matchup_features_are_also_leak_free(self):
        cutoff = "2025-05-15"
        poison = [game(999, "2025-05-16", "AAA", "BBB", 99, 0)]
        self.assertEqual(
            features.matchup_features(self.build(), "AAA", "BBB", cutoff),
            features.matchup_features(self.build(poison), "AAA", "BBB", cutoff),
        )

    def test_training_row_never_sees_its_own_game(self):
        # A row must not be able to use its own outcome as an input.
        target = game(500, "2025-05-15", "AAA", "BBB", 30, 0)
        store = store_from(list(season(days=20)) + [target])
        row = features.build_training_row(store, target)
        # 14 prior games exist (05-01..05-14); the target itself must be excluded.
        self.assertEqual(row["away_games_played"], 14)

    def test_every_row_in_a_table_is_leak_free(self):
        # End-to-end: build a table, then rebuild it with a huge future game added,
        # and assert the shared rows are identical.
        base = season(days=25)
        clean = features.build_training_table(store_from(base), require_complete=False)
        poisoned = features.build_training_table(
            store_from(list(base) + [game(999, "2025-12-01", "AAA", "BBB", 99, 0)]),
            require_complete=False,
        )
        clean_by_pk = {r["game_pk"]: r for r in clean["rows"]}
        for row in poisoned["rows"]:
            if row["game_pk"] in clean_by_pk:
                self.assertEqual(row, clean_by_pk[row["game_pk"]])


class TestSeasonScoping(unittest.TestCase):
    """A team's record resets every season. Carrying it forward is a silent bug.

    Found live: ingesting a single 2026 date into a store of 2025 games made a
    2026 prediction see the Yankees' full 163-game 2025 record as current form.
    Nothing in the output looked wrong -- the numbers were simply about the wrong
    year. Every existing test used same-year dates, so none of them caught it.
    """

    def store(self):
        last_season = [game(i, f"2025-09-{i:02d}", "AAA", "BBB", 9, 1)
                       for i in range(1, 21)]
        this_season = [game(100 + i, f"2026-04-{i:02d}", "AAA", "BBB", 1, 9)
                       for i in range(1, 4)]
        return store_from(last_season + this_season)

    def test_last_seasons_games_are_excluded_by_default(self):
        result = features.team_features(self.store(), "AAA", "2026-04-10")
        self.assertEqual(result["games_played"], 3)

    def test_last_seasons_record_does_not_leak_into_this_season(self):
        # AAA won 20 straight in 2025 and lost 3 straight in 2026. Season form must
        # reflect the 3 losses, not the 20 wins.
        result = features.team_features(self.store(), "AAA", "2026-04-10")
        self.assertEqual(result["streak"], -3)

    def test_a_thin_new_season_is_reported_thin(self):
        result = features.team_features(self.store(), "AAA", "2026-04-10")
        self.assertTrue(result["sample_is_thin"])
        self.assertIsNone(result["win_pct"])

    def test_the_previous_season_is_still_intact_within_itself(self):
        result = features.team_features(self.store(), "AAA", "2025-09-25")
        self.assertEqual(result["games_played"], 20)

    def test_scoping_can_be_disabled_deliberately(self):
        games = features.games_before(self.store(), "2026-04-10", team="AAA",
                                      same_season_only=False)
        self.assertEqual(len(games), 23)

    def test_rest_days_do_not_span_the_off_season(self):
        # Without scoping this would report a gap measured from last September,
        # letting the model key on "this is the start of a season".
        result = features.team_features(self.store(), "AAA", "2026-04-10")
        self.assertLessEqual(result["rest_days"],
                             features.MAX_MEANINGFUL_REST_DAYS)


class TestTeamFeatures(unittest.TestCase):
    def test_counts_wins_and_losses_correctly(self):
        # AAA is away and wins every game 5-2.
        store = store_from(season(days=15))
        result = features.team_features(store, "AAA", "2025-05-20")
        self.assertEqual(result["games_played"], 15)
        self.assertEqual(result["wins"], 15)
        self.assertEqual(result["losses"], 0)
        self.assertEqual(result["win_pct"], 1.0)

    def test_run_rates_are_computed(self):
        store = store_from(season(days=15))
        result = features.team_features(store, "AAA", "2025-05-20")
        self.assertAlmostEqual(result["runs_scored_pg"], 5.0)
        self.assertAlmostEqual(result["runs_allowed_pg"], 2.0)
        self.assertAlmostEqual(result["run_diff_pg"], 3.0)

    def test_losing_team_is_the_mirror_image(self):
        store = store_from(season(days=15))
        result = features.team_features(store, "BBB", "2025-05-20")
        self.assertEqual(result["wins"], 0)
        self.assertAlmostEqual(result["run_diff_pg"], -3.0)

    def test_thin_sample_suppresses_rates_but_reports_the_count(self):
        # Four games is noise wearing the costume of a signal.
        store = store_from(season(days=4))
        result = features.team_features(store, "AAA", "2025-05-20")
        self.assertEqual(result["games_played"], 4)
        self.assertTrue(result["sample_is_thin"])
        self.assertIsNone(result["win_pct"])
        self.assertIsNone(result["runs_scored_pg"])

    def test_rates_appear_once_the_threshold_is_met(self):
        store = store_from(season(days=features.MIN_GAMES_FOR_RATES))
        result = features.team_features(store, "AAA", "2025-06-01")
        self.assertFalse(result["sample_is_thin"])
        self.assertIsNotNone(result["win_pct"])

    def test_no_history_gives_zero_games_and_no_rates(self):
        result = features.team_features({}, "AAA", "2025-05-01")
        self.assertEqual(result["games_played"], 0)
        self.assertIsNone(result["win_pct"])
        self.assertIsNone(result["rest_days"])

    def test_prefix_is_applied_to_every_key(self):
        result = features.team_features({}, "AAA", "2025-05-01", prefix="away_")
        self.assertTrue(all(k.startswith("away_") for k in result))


class TestRecentForm(unittest.TestCase):
    def test_last5_counts_only_the_last_five(self):
        # 10 wins then 5 losses; last-5 must be 0 wins.
        games = [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 5, 2) for i in range(1, 11)]
        games += [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 0, 7) for i in range(11, 16)]
        result = features.team_features(store_from(games), "AAA", "2025-05-20")
        self.assertEqual(result["last5_wins"], 0)
        self.assertEqual(result["wins"], 10)

    def test_last10_spans_the_transition(self):
        games = [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 5, 2) for i in range(1, 11)]
        games += [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 0, 7) for i in range(11, 16)]
        result = features.team_features(store_from(games), "AAA", "2025-05-20")
        self.assertEqual(result["last10_wins"], 5)

    def test_incomplete_window_reports_none_rather_than_a_partial_rate(self):
        # 3 games is not a "last 5" record, and pretending otherwise understates form.
        result = features.team_features(store_from(season(days=3)), "AAA", "2025-05-20")
        self.assertEqual(result["last5_games"], 3)
        self.assertIsNone(result["last5_wins"])

    def test_form_is_not_suppressed_by_the_season_thinness_rule(self):
        # Exactly 10 games: season rates are available and so is last-10 form.
        result = features.team_features(store_from(season(days=10)), "AAA", "2025-06-01")
        self.assertEqual(result["last10_wins"], 10)


class TestSplitsRestAndStreak(unittest.TestCase):
    def test_home_and_away_splits_are_separated(self):
        games = [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 5, 2) for i in range(1, 13)]
        games += [game(20 + i, f"2025-05-{12 + i:02d}", "BBB", "AAA", 1, 9)
                  for i in range(1, 13)]
        result = features.team_features(store_from(games), "AAA", "2025-06-15")
        self.assertEqual(result["away_win_pct"], 1.0)
        self.assertEqual(result["home_win_pct"], 1.0)

    def test_rest_days_measured_from_the_last_game(self):
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1)])
        result = features.team_features(store, "AAA", "2025-05-04")
        self.assertEqual(result["rest_days"], 3)

    def test_rest_days_are_capped(self):
        store = store_from([game(1, "2025-05-01", "AAA", "BBB", 3, 1)])
        result = features.team_features(store, "AAA", "2025-09-01")
        self.assertEqual(result["rest_days"], features.MAX_MEANINGFUL_REST_DAYS)

    def test_win_streak_is_positive(self):
        self.assertEqual(
            features.team_features(store_from(season(days=6)), "AAA", "2025-06-01")["streak"], 6)

    def test_loss_streak_is_negative(self):
        self.assertEqual(
            features.team_features(store_from(season(days=6)), "BBB", "2025-06-01")["streak"], -6)

    def test_streak_stops_at_the_change(self):
        games = [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 0, 7) for i in range(1, 6)]
        games += [game(i, f"2025-05-{i:02d}", "AAA", "BBB", 5, 2) for i in range(6, 9)]
        result = features.team_features(store_from(games), "AAA", "2025-06-01")
        self.assertEqual(result["streak"], 3)


class TestExhibitionTies(unittest.TestCase):
    def test_a_tie_is_neither_a_win_nor_a_loss(self):
        games = list(season(days=10))
        games.append(game(500, "2025-05-11", "AAA", "BBB", 4, 4))
        result = features.team_features(store_from(games), "AAA", "2025-06-01")
        self.assertEqual(result["games_played"], 11)
        self.assertEqual(result["wins"], 10)
        self.assertEqual(result["losses"], 0)  # the tie is not counted as a loss

    def test_a_tie_still_contributes_runs(self):
        games = list(season(days=10))
        games.append(game(500, "2025-05-11", "AAA", "BBB", 4, 4))
        result = features.team_features(store_from(games), "AAA", "2025-06-01")
        # 10 games at 5 runs plus one at 4 = 54 over 11 games.
        self.assertAlmostEqual(result["runs_scored_pg"], 54 / 11, places=3)

    def test_a_tie_breaks_a_streak(self):
        games = list(season(days=5))
        games.append(game(500, "2025-05-06", "AAA", "BBB", 4, 4))
        self.assertEqual(
            features.team_features(store_from(games), "AAA", "2025-06-01")["streak"], 0)


class TestMatchupFeatures(unittest.TestCase):
    def test_both_sides_are_present_with_prefixes(self):
        result = features.matchup_features(store_from(season(days=15)),
                                           "AAA", "BBB", "2025-06-01")
        self.assertIn("away_win_pct", result)
        self.assertIn("home_win_pct", result)

    def test_differentials_are_home_minus_away(self):
        result = features.matchup_features(store_from(season(days=15)),
                                           "AAA", "BBB", "2025-06-01")
        # AAA (away) wins everything, so home minus away is strongly negative.
        self.assertAlmostEqual(result["diff_win_pct"], -1.0)
        self.assertAlmostEqual(result["diff_run_diff_pg"], -6.0)

    def test_differential_is_none_when_either_side_is_thin(self):
        result = features.matchup_features(store_from(season(days=3)),
                                           "AAA", "BBB", "2025-06-01")
        self.assertIsNone(result["diff_win_pct"])
        self.assertTrue(result["either_sample_thin"])


class TestTrainingTable(unittest.TestCase):
    def test_row_carries_the_label(self):
        target = game(500, "2025-05-21", "AAA", "BBB", 1, 8)
        store = store_from(list(season(days=20)) + [target])
        self.assertEqual(features.build_training_row(store, target)["home_won"], 1)

    def test_row_without_a_winner_is_rejected(self):
        tie = game(500, "2025-05-21", "AAA", "BBB", 4, 4)
        with self.assertRaises(FeatureError):
            features.build_training_row(store_from([tie]), tie)

    def test_row_missing_teams_is_rejected(self):
        broken = {"game_pk": 1, "date": "2025-05-01", "home_won": 1}
        with self.assertRaises(FeatureError):
            features.build_training_row({}, broken)

    def test_table_is_ordered_oldest_first(self):
        table = features.build_training_table(store_from(season(days=25)),
                                              require_complete=False)
        dates = [r["date"] for r in table["rows"]]
        self.assertEqual(dates, sorted(dates))

    def test_thin_rows_are_excluded_and_counted(self):
        table = features.build_training_table(store_from(season(days=25)))
        self.assertGreater(table["skipped"]["thin_sample"], 0)
        self.assertTrue(all(not r["either_sample_thin"] for r in table["rows"]))

    def test_require_complete_false_keeps_early_rows(self):
        strict = features.build_training_table(store_from(season(days=25)))
        loose = features.build_training_table(store_from(season(days=25)),
                                              require_complete=False)
        self.assertGreater(loose["count"], strict["count"])

    def test_ties_are_counted_as_skipped_not_silently_dropped(self):
        games = list(season(days=25))
        games.append(game(500, "2025-06-01", "AAA", "BBB", 4, 4))
        table = features.build_training_table(store_from(games))
        self.assertEqual(table["skipped"]["no_label"], 1)

    def test_date_range_filters_are_applied(self):
        table = features.build_training_table(store_from(season(days=25)),
                                              min_date="2025-05-10",
                                              max_date="2025-05-15",
                                              require_complete=False)
        self.assertTrue(all("2025-05-10" <= r["date"] <= "2025-05-15"
                            for r in table["rows"]))

    def test_base_rate_is_reported(self):
        table = features.build_training_table(store_from(season(days=25)),
                                              require_complete=False)
        # AAA (away) wins every game, so the home base rate is 0.
        self.assertEqual(table["base_rate"], 0.0)

    def test_empty_store_produces_an_empty_table_not_an_error(self):
        table = features.build_training_table({})
        self.assertEqual(table["count"], 0)
        self.assertIsNone(table["base_rate"])


if __name__ == "__main__":
    unittest.main()
