"""src/situation/series.py: postseason series rebuilt from game results."""

from __future__ import annotations

import unittest

from src.situation import series as ser
from tests import situation_fixtures as F


def by_teams(all_series, a, b, game_type):
    pair = tuple(sorted((a, b)))
    return next(s for s in all_series if s.teams == pair and s.game_type == game_type)


class TheFormats(unittest.TestCase):
    def test_wins_needed_by_round(self):
        self.assertEqual(ser.wins_needed(2025, "D"), 3)
        self.assertEqual(ser.wins_needed(2025, "L"), 4)
        self.assertEqual(ser.wins_needed(2025, "W"), 4)

    def test_the_wild_card_round_changed_with_the_seasons(self):
        for season in (2015, 2019, 2021):
            self.assertEqual(ser.wins_needed(season, "F"), 1, season)     # a single game
        for season in (2020, 2022, 2025):
            self.assertEqual(ser.wins_needed(season, "F"), 2, season)     # best of three
        self.assertEqual(ser.wild_card_series_expected(2019), 2)
        self.assertEqual(ser.wild_card_series_expected(2020), 8)
        self.assertEqual(ser.wild_card_series_expected(2024), 4)

    def test_a_stored_series_length_overrides_the_table(self):
        self.assertEqual(ser.wins_needed(2019, "F", 3), 2)
        self.assertEqual(ser.wins_needed(2025, "D", 5), 3)

    def test_the_length_in_words(self):
        self.assertEqual(ser.series_length_words(2019, "F"), "a single game")
        self.assertEqual(ser.series_length_words(2025, "D"), "best of 5")
        self.assertEqual(ser.series_length_words(2025, "W"), "best of 7")

    def test_the_round_before(self):
        self.assertIsNone(ser.previous_round("F"))
        self.assertEqual([ser.previous_round(r) for r in "DLW"], ["F", "D", "L"])


class TheRowHelpers(unittest.TestCase):
    def test_a_winner_comes_from_the_score_first(self):
        row = F.g(1, "2025-10-01", "BOS", "TB", 5, 3)
        self.assertEqual(ser.winner_of(row), "BOS")
        row["winner"] = "TB"                       # a stored winner that contradicts the score loses
        self.assertEqual(ser.winner_of(row), "BOS")

    def test_a_tie_or_an_unscored_game_has_no_winner(self):
        row = F.g(1, "2025-10-01", "BOS", "TB", 3, 3)
        self.assertIsNone(ser.winner_of(row))
        row = F.g(1, "2025-10-01", "BOS", "TB", 3, 4)
        row["away_score"] = row["home_score"] = None
        row["winner"] = "TB"
        self.assertEqual(ser.winner_of(row), "TB")          # the store's own winner, when there is no score
        row["winner"] = "XXX"
        self.assertIsNone(ser.winner_of(row))

    def test_dates_are_read_strictly(self):
        self.assertEqual(ser.row_date({"date": "2025-10-01T00:00:00Z"}), "2025-10-01")
        self.assertIsNone(ser.row_date({"date": "10/01/2025"}))
        self.assertIsNone(ser.row_date({}))
        self.assertEqual(ser.days_between("2025-10-01", "2025-10-04"), 3)


class TheSeries(unittest.TestCase):
    def setUp(self):
        self.all = ser.build_series(F.world())

    def test_it_finds_every_postseason_series_and_no_regular_season_one(self):
        self.assertEqual(len(self.all), 5)          # four Wild Card series and the Division Series
        self.assertEqual({s.game_type for s in self.all}, {"F", "D"})

    def test_a_series_score_winner_and_length(self):
        wc = by_teams(self.all, "TB", "BOS", "F")
        self.assertEqual(wc.wins, {"BOS": 1, "TB": 2})
        self.assertEqual((wc.winner, wc.loser, wc.length, wc.complete), ("TB", "BOS", 3, True))
        self.assertEqual((wc.first_date, wc.last_date), ("2025-09-30", "2025-10-02"))
        ds = by_teams(self.all, "NYY", "TB", "D")
        self.assertEqual(ds.wins, {"NYY": 3, "TB": 2})
        self.assertEqual((ds.winner, ds.length, ds.needed), ("NYY", 5, 3))

    def test_the_cutoff_gives_the_series_going_into_a_game(self):
        before = ser.build_series(F.world(), before="2025-10-08")
        ds = by_teams(before, "NYY", "TB", "D")
        self.assertEqual(ds.length, 3)
        self.assertEqual(ds.wins, {"NYY": 2, "TB": 1})
        self.assertFalse(ds.complete)
        self.assertIsNone(ds.winner)

    def test_a_series_with_no_games_before_the_cutoff_does_not_exist_yet(self):
        before = ser.build_series(F.world(), before="2025-10-04")
        self.assertEqual({s.game_type for s in before}, {"F"})

    def test_a_game_on_the_cutoff_date_does_not_count(self):
        before = ser.build_series(F.world(), before="2025-10-02")
        wc = by_teams(before, "TB", "BOS", "F")
        self.assertEqual(wc.length, 2)

    def test_rows_in_any_order_give_the_same_series(self):
        rows = F.world()
        a = ser.build_series(rows)
        b = ser.build_series(list(reversed(rows)))
        self.assertEqual([(s.season, s.game_type, s.teams, s.wins) for s in a],
                         [(s.season, s.game_type, s.teams, s.wins) for s in b])

    def test_a_duplicate_row_is_one_game(self):
        rows = F.world() + [dict(F.division_series()[0])]
        ds = by_teams(ser.build_series(rows), "NYY", "TB", "D")
        self.assertEqual(ds.length, 5)

    def test_a_single_game_wild_card_is_decided_by_its_one_game(self):
        rows = [F.g(1, "2019-10-02", "OAK", "TB", 1, 5, "F")]
        s = ser.build_series(rows)[0]
        self.assertTrue(s.complete)
        self.assertEqual(s.winner, "TB")

    def test_an_unscored_or_dateless_row_is_skipped(self):
        bad = F.g(1, "2025-10-01", "BOS", "TB", 3, 3, "F")
        nodate = dict(F.g(2, "2025-10-01", "BOS", "TB", 4, 3, "F"), date=None)
        self.assertEqual(ser.build_series([bad, nodate]), [])


class TheBye(unittest.TestCase):
    def setUp(self):
        self.all = ser.build_series(F.world(), before="2025-10-04")

    def test_a_club_that_played_the_round_before_is_played_with_that_series(self):
        status, s = ser.bye_or_played(self.all, "TB", 2025, "D")
        self.assertEqual(status, "played")
        self.assertEqual((s.game_type, s.winner), ("F", "TB"))

    def test_a_club_with_no_wild_card_game_had_a_bye_only_when_the_round_is_all_in_the_data(self):
        self.assertEqual(ser.bye_or_played(self.all, "NYY", 2025, "D"), ("bye", None))
        self.assertTrue(ser.wild_card_round_complete(self.all, 2025))

    def test_with_the_wild_card_round_missing_a_club_is_unknown_not_rested(self):
        only_ds = [r for r in F.world() if r["game_type"] != "F"]
        s = ser.build_series(only_ds, before="2025-10-04")
        self.assertEqual(ser.bye_or_played(s, "NYY", 2025, "D"), ("unknown", None))

    def test_with_the_round_partly_in_the_data_a_club_is_unknown(self):
        partial = [r for r in F.world() if r["game_type"] != "F" or r["game_pk"] in ("301", "302", "303")]
        s = ser.build_series(partial, before="2025-10-04")
        self.assertFalse(ser.wild_card_round_complete(s, 2025))
        self.assertEqual(ser.bye_or_played(s, "NYY", 2025, "D"), ("unknown", None))

    def test_the_wild_card_round_has_no_round_before_it(self):
        self.assertEqual(ser.bye_or_played(self.all, "TB", 2025, "F"), ("none", None))

    def test_the_league_championship_series_has_no_byes(self):
        # nobody skips the Division Series
        self.assertEqual(ser.bye_or_played(self.all, "NYY", 2025, "L")[0], "unknown")

    def test_every_club_played_in_2020(self):
        rows = [F.g(1, "2020-09-29", "A", "B", 2, 1, "F"), F.g(2, "2020-09-30", "A", "B", 2, 1, "F")]
        s = ser.build_series(rows)
        self.assertEqual(ser.bye_or_played(s, "A", 2020, "D")[0], "played")


if __name__ == "__main__":
    unittest.main()
