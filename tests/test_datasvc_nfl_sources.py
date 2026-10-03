"""src/datasvc/nfl/sources.py: every nflverse file read into the contract's shapes, offline.

Real excerpts of the four files are saved in tests/fixtures/nflverse/ (cut from the files fetched on
2026-10-03 by `scripts`-free hand: the rows are real, nothing is edited); the cases the real rows
do not contain (a game in progress, a duplicate player, a quarterback with no id) are written here as
synthetic rows in the same columns. No test touches the network.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.datasvc.http import NotFound
from src.datasvc.nfl import sources
from tests._nfl_world import FakeFetcher

FIX = Path(__file__).parent / "fixtures" / "nflverse"
FETCHED = "2026-10-03T21:25:30Z"


def fixture(name: str) -> list:
    return sources.read_csv((FIX / name).read_text(encoding="utf-8"))


def game_row(**over) -> dict:
    """A games.csv row with every column blank except what a test sets."""
    row = {c: "" for c in fixture("games_excerpt.csv")[0]}
    row.update({"game_id": "2025_09_AAA_BBB", "season": "2025", "game_type": "REG", "week": "9",
                "gameday": "2025-11-02", "weekday": "Sunday", "gametime": "13:00", "away_team": "AAA", "home_team": "BBB",
                "location": "Home", "stadium_id": "BBB00", "stadium": "B Stadium"})
    row.update(over)
    return row


class ReadingCsv(unittest.TestCase):
    def test_a_quoted_field_with_a_line_break_stays_in_its_row(self):
        text = 'a,b,c\n1,"two\n    ",3\n4,5,6\n'
        self.assertEqual(sources.read_csv(text), [{"a": "1", "b": "two\n    ", "c": "3"}, {"a": "4", "b": "5", "c": "6"}])

    def test_a_byte_order_mark_does_not_rename_the_first_column(self):
        self.assertEqual(sources.read_csv("﻿game_id,season\nx,2025\n"), [{"game_id": "x", "season": "2025"}])

    def test_the_real_injury_file_excerpt_keeps_its_multi_line_practice_status(self):
        rows = fixture("injuries_excerpt_2024.csv")
        self.assertEqual(len(rows), 9)                       # splitlines() would have made 11 broken ones
        self.assertEqual(sum(1 for r in rows if r["practice_status"].strip() == "" and "\n" in r["practice_status"]), 4)

    def test_scalars(self):
        self.assertEqual(sources.to_number("7"), 7)
        self.assertIsInstance(sources.to_number("7.0"), int)
        self.assertEqual(sources.to_number("3.5"), 3.5)
        for blank in ("", "  ", "NA", "N/A", "nan", "NaN", None, "None"):
            self.assertIsNone(sources.to_number(blank), repr(blank))
        self.assertIsNone(sources.to_number("abc"))
        self.assertIsNone(sources.to_number("inf"))
        self.assertEqual(sources.to_int("7.0"), 7)
        self.assertIsNone(sources.to_int("3.5"))
        self.assertEqual(sources.to_float("0.123456789", 4), 0.1235)
        self.assertIs(sources.to_flag("1"), True)
        self.assertIs(sources.to_flag("0"), False)
        self.assertIsNone(sources.to_flag(""))
        self.assertIsNone(sources.to_flag("maybe"))


class TheSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games, cls.info = sources.parse_games(fixture("games_excerpt.csv"), fetched_utc=FETCHED)
        cls.by_id = {g["game_id"]: g for g in cls.games}

    def test_a_real_thursday_night_game_in_every_field(self):
        g = self.by_id["2025_01_DAL_PHI"]
        self.assertEqual({k: g[k] for k in ("season", "week", "game_type", "gameday", "weekday", "kickoff_et",
                                            "kickoff_utc", "status", "home_team", "away_team", "home_score",
                                            "away_score", "overtime", "neutral_site")},
                         {"season": 2025, "week": 1, "game_type": "REG", "gameday": "2025-09-04", "weekday": "Thursday",
                          "kickoff_et": "20:20", "kickoff_utc": "2025-09-05T00:20:00Z", "status": "final",
                          "home_team": "PHI", "away_team": "DAL", "home_score": 24, "away_score": 20,
                          "overtime": False, "neutral_site": False})
        self.assertEqual((g["stadium_id"], g["stadium"], g["venue_check"], g["roof"], g["surface"], g["temp_f"],
                          g["wind_mph"], g["div_game"]), ("PHI00", "Lincoln Financial Field", "ok", "outdoors", "grass",
                                                          75, 11, True))
        self.assertEqual((g["home_rest_days"], g["away_rest_days"], g["home_coach"], g["away_coach"], g["referee"]),
                         (7, 7, "Nick Sirianni", "Brian Schottenheimer", "Shawn Smith"))
        self.assertEqual((g["home_qb_id"], g["home_qb_name"], g["away_qb_id"], g["away_qb_name"]),
                         ("00-0036389", "Jalen Hurts", "00-0033077", "Dak Prescott"))
        self.assertEqual((g["spread_line"], g["total_line"], g["home_moneyline"], g["away_moneyline"],
                          g["home_spread_odds"], g["over_odds"]), (8.5, 47.5, -425, 330, -110, -110))
        self.assertEqual((g["source"], g["fetched_utc"]), ("nflverse:games.csv", FETCHED))

    def test_kickoffs_after_the_clocks_change_use_standard_time(self):
        # 2021_15_NE_IND was a Saturday 20:20 Eastern game in December: 01:20 UTC the next day, not 00:20
        self.assertEqual(self.by_id["2021_15_NE_IND"]["kickoff_utc"], "2021-12-19T01:20:00Z")
        self.assertEqual(self.by_id["2026_01_SF_LA"]["kickoff_utc"], "2026-09-11T00:35:00Z")          # the Melbourne opener

    def test_a_game_not_yet_played_has_a_projected_quarterback_and_no_scores(self):
        g = self.by_id["2026_04_GB_TB"]
        self.assertEqual((g["status"], g["home_score"], g["away_score"], g["overtime"], g["temp_f"]),
                         ("scheduled", None, None, None, None))
        self.assertEqual((g["away_qb_name"], g["home_qb_name"]), ("Jordan Love", "Jalon Daniels"))
        self.assertEqual((g["spread_line"], g["away_moneyline"], g["home_moneyline"]), (-3.0, -170, 142))

    def test_a_trailing_space_in_the_surface_is_trimmed(self):
        spaced = [g for g in self.games if g["season"] == 2021 and g["game_id"].startswith("2021_0")]
        self.assertTrue(spaced)
        self.assertEqual({g["surface"] for g in spaced if g["surface"] and g["surface"].startswith("grass")}, {"grass"})

    def test_the_two_venues_the_schedule_names_wrongly_are_flagged_and_no_other_is(self):
        flagged = {g["game_id"]: g["venue_check"] for g in self.games if g["venue_check"] != "ok"}
        self.assertEqual(flagged, {"2025_04_MIN_PIT": "nominal_home_stadium_on_neutral_site",
                                   "2026_05_PHI_JAX": "stadium_id_name_conflict"})
        self.assertEqual(self.info["venue_check"], {"nominal_home_stadium_on_neutral_site": 1,
                                                    "stadium_id_name_conflict": 1})
        # the neutral games with a real venue are not flagged: Melbourne, Munich, the Super Bowl
        for gid in ("2026_01_SF_LA", "2024_10_NYG_CAR", "2025_22_SEA_NE", "2021_01_GB_NO"):
            if gid in self.by_id:
                self.assertEqual(self.by_id[gid]["venue_check"], "ok", gid)

    def test_a_neutral_game_at_a_stadium_two_teams_share_is_flagged_through_the_nominal_home_team(self):
        rows = [game_row(game_id="2025_01_AAA_LAC", season="2025", home_team="LAC", away_team="AAA", location="Home",
                         stadium_id="LAX01", stadium="SoFi Stadium"),
                game_row(game_id="2025_02_AAA_LAC", season="2025", week="2", home_team="LAC", away_team="AAA",
                         location="Home", stadium_id="LAX01", stadium="SoFi Stadium"),
                game_row(game_id="2025_01_KC_LAC", season="2025", home_team="LAC", away_team="KC", location="Neutral",
                         stadium_id="LAX01", stadium="SoFi Stadium")]       # really played in Sao Paulo
        games, _ = sources.parse_games(rows, fetched_utc=FETCHED)
        self.assertEqual({g["game_id"]: g["venue_check"] for g in games},
                         {"2025_01_AAA_LAC": "ok", "2025_02_AAA_LAC": "ok",
                          "2025_01_KC_LAC": "nominal_home_stadium_on_neutral_site"})

    def test_the_seasons_filter_keeps_the_whole_file_for_context_but_returns_only_those_seasons(self):
        games, info = sources.parse_games(fixture("games_excerpt.csv"), fetched_utc=FETCHED, seasons=[2026])
        self.assertTrue(games and all(g["season"] == 2026 for g in games))
        self.assertEqual({g["game_id"] for g in games if g["venue_check"] != "ok"}, {"2026_05_PHI_JAX"})
        self.assertEqual(info["rows"], 60)

    def test_a_row_that_cannot_be_understood_is_skipped_and_counted(self):
        rows = [game_row(), game_row(game_id="", season="2025"), game_row(season="twenty"), game_row(week="x"),
                game_row(gameday="", game_id="2025_09_CCC_DDD")]
        games, info = sources.parse_games(rows, fetched_utc=FETCHED)
        self.assertEqual((len(games), info["skipped_rows"]), (1, 4))

    def test_a_blank_kickoff_time_gives_no_kickoff_and_a_scheduled_game(self):
        games, _ = sources.parse_games([game_row(gametime="")], fetched_utc=FETCHED)
        self.assertEqual((games[0]["kickoff_et"], games[0]["kickoff_utc"], games[0]["status"]), (None, None, "scheduled"))


class TheStatusOfAGame(unittest.TestCase):
    """final, in_progress, scheduled, no_result: decided from the scores and the fetch time."""

    KICKOFF = "2025-11-02T18:00:00Z"        # 13:00 Eastern, after the clocks changed that morning

    def status(self, fetched, **over):
        games, _ = sources.parse_games([game_row(**over)], fetched_utc=fetched)
        return games[0]["status"]

    def test_scores_long_after_kickoff_are_a_final(self):
        self.assertEqual(self.status("2025-11-02T21:00:00Z", home_score="24", away_score="20", overtime="0"), "final")
        self.assertEqual(self.status("2025-11-02T20:30:00Z", home_score="24", away_score="20"), "final")   # exactly 150 minutes

    def test_scores_seen_sooner_than_any_game_can_end_are_a_game_in_progress(self):
        self.assertEqual(self.status("2025-11-02T20:29:59Z", home_score="14", away_score="10"), "in_progress")
        self.assertEqual(self.status("2025-11-02T18:05:00Z", home_score="0", away_score="0"), "in_progress")

    def test_no_scores_before_kickoff_is_scheduled(self):
        self.assertEqual(self.status("2025-10-30T12:00:00Z"), "scheduled")

    def test_no_scores_long_after_kickoff_is_no_result_not_scheduled(self):
        self.assertEqual(self.status("2025-11-02T23:00:00Z"), "scheduled")          # a few hours: may still be updating
        self.assertEqual(self.status("2025-11-03T06:00:01Z"), "no_result")          # 12 hours and a second
        self.assertEqual(self.status("2026-10-03T00:00:00Z"), "no_result")

    def test_one_score_alone_is_not_a_result(self):
        self.assertEqual(self.status("2025-11-03T12:00:00Z", home_score="24"), "no_result")

    def test_a_score_with_no_kickoff_time_is_a_final(self):
        self.assertEqual(self.status("2025-11-03T12:00:00Z", gametime="", home_score="24", away_score="20"), "final")

    def test_overtime_is_null_until_there_is_a_score(self):
        games, _ = sources.parse_games([game_row(overtime="0"), game_row(game_id="x", home_score="3", away_score="0", overtime="1")],
                                       fetched_utc="2025-11-03T12:00:00Z")
        self.assertEqual([g["overtime"] for g in games], [None, True])


class TeamStatistics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats, cls.info = sources.parse_team_stats(fixture("stats_team_excerpt_2025.csv"))
        cls.games = {g["game_id"]: g for g in sources.parse_games(fixture("games_excerpt.csv"), fetched_utc=FETCHED)[0]}

    def test_four_rows_two_games(self):
        self.assertEqual(self.info, {"rows": 4, "team_rows": 4, "skipped_rows": 0, "duplicates": 0})
        self.assertEqual(sorted(self.stats), [("2025_01_ARI_NO", "ARI"), ("2025_01_ARI_NO", "NO"),
                                              ("2025_01_DAL_PHI", "DAL"), ("2025_01_DAL_PHI", "PHI")])

    def test_sack_yards_are_stored_positive_though_the_source_writes_them_negative(self):
        row = {r["team"]: r for r in fixture("stats_team_excerpt_2025.csv") if r["game_id"] == "2025_01_ARI_NO"}
        self.assertEqual(row["ARI"]["sack_yards_lost"], "-33")
        self.assertEqual(self.stats[("2025_01_ARI_NO", "ARI")]["sack_yards_lost"], 33)
        self.assertEqual(self.stats[("2025_01_DAL_PHI", "DAL")]["sack_yards_lost"], 0)

    def test_a_real_row_in_every_stored_statistic(self):
        self.assertEqual(self.stats[("2025_01_DAL_PHI", "PHI")], {
            "pass_attempts": 23, "completions": 19, "passing_yards": 152, "passing_tds": 0, "interceptions": 0,
            "sacks_taken": 1, "sack_yards_lost": 8, "carries": 38, "rushing_yards": 158, "rushing_tds": 3,
            "fumbles_lost": 0, "penalties": 9, "penalty_yards": 110, "passing_first_downs": 6, "rushing_first_downs": 14,
            "passing_epa": 1.591, "rushing_epa": 6.045, "sacks_made": 0, "def_interceptions": 0})

    def test_a_blank_statistic_is_null_not_zero_and_unreadable_rows_are_counted(self):
        good = {"game_id": "g1", "team": "AAA", "attempts": "", "carries": "20"}
        stats, info = sources.parse_team_stats([good, {"game_id": "", "team": "BBB"}, {"game_id": "g2", "team": ""},
                                                dict(good)])
        self.assertIsNone(stats[("g1", "AAA")]["pass_attempts"])
        self.assertEqual(stats[("g1", "AAA")]["carries"], 20)
        self.assertEqual((info["skipped_rows"], info["duplicates"], info["team_rows"]), (2, 1, 1))

    def test_team_games_by_hand(self):
        """PHI: 23 attempts + 1 sack + 38 carries = 62 plays; net yards 152 - 8 + 158 = 302; 4.871 a play.
        DAL: 34 + 0 + 22 = 56 plays; 188 - 0 + 119 = 307; 5.4821 a play. DAL lost a fumble, PHI none."""
        game = self.games["2025_01_DAL_PHI"]
        rows = sources.build_team_games([game], {k: v for k, v in self.stats.items() if k[0] == game["game_id"]},
                                        fetched_utc=FETCHED, stats_source="nflverse:stats_team_week_2025")
        phi, dal = ({r["team"]: r for r in rows}[t] for t in ("PHI", "DAL"))
        self.assertEqual((len(rows), phi["site"], dal["site"], phi["opponent"], dal["opponent"]), (2, "home", "away", "DAL", "PHI"))
        self.assertEqual((phi["plays"], phi["net_yards"], phi["yards_per_play"]), (62, 302, 4.871))
        self.assertEqual((dal["plays"], dal["net_yards"], dal["yards_per_play"]), (56, 307, 5.4821))
        self.assertEqual((phi["giveaways"], phi["takeaways"], phi["turnover_margin"]), (0, 1, 1))
        self.assertEqual((dal["giveaways"], dal["takeaways"], dal["turnover_margin"]), (1, 0, -1))
        self.assertEqual((phi["points_for"], phi["points_against"], phi["margin"], phi["result"]), (24, 20, 4, "W"))
        self.assertEqual((dal["points_for"], dal["points_against"], dal["margin"], dal["result"]), (20, 24, -4, "L"))
        self.assertEqual((phi["qb_name"], phi["coach"], phi["rest_days_source"]), ("Jalen Hurts", "Nick Sirianni", 7))
        self.assertEqual(phi["source"], "nflverse:games.csv+stats_team_week_2025")
        self.assertTrue(phi["has_stats"] and dal["has_stats"])

    def test_a_games_two_turnover_margins_always_sum_to_zero(self):
        # 2025_01_ARI_NO is not in the schedule excerpt: build a game for it (scores are not what is tested here)
        game = game_row(game_id="2025_01_ARI_NO", home_team="NO", away_team="ARI", home_score="13", away_score="20")
        games, _ = sources.parse_games([game], fetched_utc="2026-10-03T00:00:00Z")
        rows = sources.build_team_games(games, self.stats, fetched_utc=FETCHED, stats_source="nflverse:stats_team_week_2025")
        self.assertEqual(sum(r["turnover_margin"] for r in rows), 0)
        self.assertEqual({r["team"]: r["plays"] for r in rows}, {"ARI": 61, "NO": 69})        # 29+5+27 ; 46+1+22
        self.assertEqual({r["team"]: r["net_yards"] for r in rows}, {"ARI": 276, "NO": 315})   # 163-33+146 ; 214-6+107

    def test_a_game_with_no_statistics_row_has_null_statistics_and_says_so(self):
        game = self.games["2025_01_DAL_PHI"]
        rows = sources.build_team_games([game], {}, fetched_utc=FETCHED)
        for row in rows:
            self.assertFalse(row["has_stats"])
            self.assertEqual((row["pass_attempts"], row["plays"], row["net_yards"], row["giveaways"], row["takeaways"],
                              row["turnover_margin"]), (None,) * 6)
            self.assertEqual(row["source"], "nflverse:games.csv")
        self.assertEqual({r["result"] for r in rows}, {"W", "L"})            # the score is the schedule's, not the statistics'

    def test_a_missing_opponent_row_leaves_takeaways_and_the_margin_null(self):
        game = self.games["2025_01_DAL_PHI"]
        only_phi = {k: v for k, v in self.stats.items() if k == ("2025_01_DAL_PHI", "PHI")}
        rows = {r["team"]: r for r in sources.build_team_games([game], only_phi, fetched_utc=FETCHED)}
        self.assertEqual((rows["PHI"]["giveaways"], rows["PHI"]["takeaways"], rows["PHI"]["turnover_margin"]), (0, None, None))
        self.assertEqual(rows["PHI"]["plays"], 62)
        self.assertFalse(rows["DAL"]["has_stats"])

    def test_a_game_not_yet_played_gets_two_rows_with_no_result(self):
        rows = sources.build_team_games([self.games["2026_04_GB_TB"]], {}, fetched_utc=FETCHED)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual((row["points_for"], row["margin"], row["result"], row["status"], row["has_stats"]),
                             (None, None, None, "scheduled", False))
        self.assertEqual({r["qb_name"] for r in rows}, {"Jordan Love", "Jalon Daniels"})     # projected starters

    def test_a_neutral_site_game_is_neutral_for_both_teams(self):
        rows = sources.build_team_games([self.games["2026_01_SF_LA"]], {}, fetched_utc=FETCHED)
        self.assertEqual({r["site"] for r in rows}, {"neutral"})

    def test_an_in_progress_game_has_no_result_and_no_margin(self):
        game = game_row(home_score="14", away_score="10")
        games, _ = sources.parse_games([game], fetched_utc="2025-11-02T18:30:00Z")
        rows = sources.build_team_games(games, {}, fetched_utc=FETCHED)
        self.assertEqual({(r["status"], r["result"], r["margin"]) for r in rows}, {("in_progress", None, None)})
        self.assertEqual({r["points_for"] for r in rows}, {14, 10})


class PlayerStatistics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = {g["game_id"]: g for g in sources.parse_games(fixture("games_excerpt.csv"), fetched_utc=FETCHED)[0]}
        cls.rows, cls.info = sources.parse_player_stats(fixture("stats_player_excerpt_2025.csv"), cls.games,
                                                        fetched_utc=FETCHED, source="nflverse:stats_player_week_2025")
        cls.by_id = {r["player_id"]: r for r in cls.rows}

    def test_the_rows_that_are_kept_and_the_ones_that_are_not(self):
        self.assertEqual(self.info, {"rows": 19, "kept": 14, "dropped_not_offense": 4, "dropped_no_player_id": 1})
        self.assertEqual(self.info["rows"], self.info["kept"] + self.info["dropped_not_offense"] + self.info["dropped_no_player_id"])
        self.assertNotIn("00-0033787", self.by_id)               # a kicker
        self.assertNotIn("00-0033877", self.by_id)               # a safety with no usage
        self.assertIn("00-0037614", self.by_id)                  # a wide receiver with a stat line of zeros: a game played

    def test_a_receiver_in_every_field(self):
        lamb = self.by_id["00-0036358"]
        self.assertEqual({k: lamb[k] for k in ("game_id", "season", "week", "game_type", "kickoff_utc", "team", "opponent",
                                               "name", "position", "position_group", "targets", "receptions",
                                               "receiving_yards", "receiving_tds", "target_share", "pass_attempts",
                                               "carries")},
                         {"game_id": "2025_01_DAL_PHI", "season": 2025, "week": 1, "game_type": "REG",
                          "kickoff_utc": "2025-09-05T00:20:00Z", "team": "DAL", "opponent": "PHI", "name": "CeeDee Lamb",
                          "position": "WR", "position_group": "WR", "targets": 13, "receptions": 7,
                          "receiving_yards": 110, "receiving_tds": 0, "target_share": 0.3939, "pass_attempts": 0,
                          "carries": 0})
        self.assertEqual((lamb["source"], lamb["fetched_utc"]), ("nflverse:stats_player_week_2025", FETCHED))

    def test_a_quarterback_who_also_ran(self):
        hurts = self.by_id["00-0036389"]
        self.assertEqual((hurts["pass_attempts"], hurts["completions"], hurts["carries"], hurts["position_group"]),
                         (23, 19, 14, "QB"))

    def test_shares_are_rounded_to_four_decimals(self):
        self.assertEqual(self.by_id["00-0035243"]["target_share"], 0.0303)

    def test_the_rows_are_keyed_by_game_and_player_and_a_repeat_is_counted(self):
        source = fixture("stats_player_excerpt_2025.csv")
        rows, info = sources.parse_player_stats(source + [dict(source[0])], self.games, fetched_utc=FETCHED, source="s")
        self.assertEqual(info["duplicates"], 1)
        self.assertEqual(info["rows"], info["kept"] + info["duplicates"] + info["dropped_not_offense"] + info["dropped_no_player_id"])
        self.assertEqual(len({(r["game_id"], r["player_id"]) for r in rows}), len(rows))

    def test_a_defender_with_a_carry_is_kept_and_a_row_for_an_unknown_game_is_not(self):
        source = fixture("stats_player_excerpt_2025.csv")
        defender = dict(next(r for r in source if r["position"] == "FS"), carries="1", rushing_yards="2")
        stranger = dict(source[0], game_id="2025_99_XXX_YYY")
        rows, info = sources.parse_player_stats([defender, stranger], self.games, fetched_utc=FETCHED, source="s")
        self.assertEqual([r["player_id"] for r in rows], ["00-0033877"])
        self.assertEqual((rows[0]["carries"], rows[0]["position_group"]), (1, "DB"))
        self.assertEqual(info["dropped_unknown_game"], 1)


class InjuryReports(unittest.TestCase):
    def games_for(self, season, entries):
        out = {}
        for week, team, game_id in entries:
            out[(season, week, team)] = {"game_id": game_id, "game_type": "REG"}
        return out

    def test_the_2024_excerpt_with_timestamps_duplicates_and_blank_positions(self):
        games = self.games_for(2024, [(1, "ARI", "2024_01_ARI_BUF"), (15, "HOU", "2024_15_HOU_KC"), (15, "NYJ", "2024_15_NYJ_JAX"),
                                      (1, "CLE", "2024_01_CLE_DAL"), (1, "KC", "2024_01_BAL_KC")])
        rows, info = sources.parse_injuries(fixture("injuries_excerpt_2024.csv"), games, fetched_utc=FETCHED,
                                            source="nflverse:injuries_2024")
        self.assertEqual(info, {"rows": 9, "kept": 5, "duplicates": 2, "dropped_full_participation_only": 2})
        self.assertEqual(info["rows"], info["kept"] + info["duplicates"] + info["dropped_full_participation_only"])
        by = {(r["game_id"], r["player_id"]): r for r in rows}
        # a player listed twice in a week keeps the row with the later timestamp: Questionable then Out is Out
        hou = by[("2024_15_HOU_KC", "00-0039359")]
        self.assertEqual((hou["report_status"], hou["date_modified"]), ("out", "2024-12-15T14:17:06Z"))
        self.assertEqual(by[("2024_15_NYJ_JAX", "00-0034270")]["report_status"], "out")
        # the multi-line practice status is blank, so null
        self.assertIsNone(hou["practice_status"])
        wr = by[("2024_01_ARI_BUF", "00-0039521")]
        self.assertEqual((wr["report_status"], wr["practice_status"], wr["position"], wr["position_group"], wr["team"],
                          wr["season"], wr["week"], wr["name"], wr["report_injury"], wr["date_modified"]),
                         ("out", "dnp", "WR", "WR", "ARI", 2024, 1, "Xavier Weaver", "Oblique", "2024-09-06T19:05:30Z"))
        self.assertEqual(by[("2024_01_ARI_BUF", "00-0037141")]["position_group"], "DB")       # a safety
        self.assertEqual(by[("2024_01_ARI_BUF", "00-0037141")]["practice_status"], "limited")

    def test_a_row_that_is_only_full_participation_is_not_stored_and_a_blank_position_is_null(self):
        games = self.games_for(2024, [(1, "CLE", "g1"), (1, "KC", "g2")])
        rows, info = sources.parse_injuries([r for r in fixture("injuries_excerpt_2024.csv") if r["team"] in ("CLE", "KC")],
                                            games, fetched_utc=FETCHED, source="s")
        self.assertEqual((rows, info["dropped_full_participation_only"]), ([], 2))

    def test_the_2025_file_has_no_timestamp(self):
        games = self.games_for(2025, [(1, "DAL", "2025_01_DAL_PHI")])
        rows, info = sources.parse_injuries(fixture("injuries_excerpt_2025.csv"), games, fetched_utc=FETCHED,
                                            source="nflverse:injuries_2025")
        self.assertEqual((info["rows"], info["kept"], info["dropped_full_participation_only"]), (4, 1, 3))
        self.assertEqual((rows[0]["position"], rows[0]["position_group"], rows[0]["report_status"], rows[0]["practice_status"],
                          rows[0]["date_modified"]), ("DT", "DL", "out", "dnp", None))

    def test_a_row_for_a_team_with_no_game_that_week_is_counted_not_stored(self):
        rows, info = sources.parse_injuries(fixture("injuries_excerpt_2025.csv"), {}, fetched_utc=FETCHED, source="s")
        self.assertEqual((rows, info["dropped_no_game"]), ([], 4))

    def test_unknown_status_text_is_kept_lower_cased_rather_than_dropped(self):
        row = {"season": "2025", "week": "3", "team": "KC", "gsis_id": "00-1", "position": "QB", "full_name": "Q",
               "report_status": "Suspension", "practice_status": "Did Not Participate In Practice"}
        rows, _ = sources.parse_injuries([row], self.games_for(2025, [(3, "KC", "g")]), fetched_utc=FETCHED, source="s")
        self.assertEqual((rows[0]["report_status"], rows[0]["practice_status"]), ("suspension", "dnp"))

    def test_an_unreadable_timestamp_is_null_and_a_duplicate_without_one_keeps_the_later_line(self):
        a = {"season": "2025", "week": "3", "team": "KC", "gsis_id": "00-1", "position": "QB", "full_name": "Q",
             "report_status": "Questionable", "date_modified": "not a time"}
        b = dict(a, report_status="Out")
        rows, info = sources.parse_injuries([a, b], self.games_for(2025, [(3, "KC", "g")]), fetched_utc=FETCHED, source="s")
        self.assertEqual((len(rows), info["duplicates"], rows[0]["report_status"], rows[0]["date_modified"]), (1, 1, "out", None))


class Fetching(unittest.TestCase):
    URL = sources.team_stats_url(2025)

    def test_a_404_is_none_not_an_error(self):
        self.assertEqual(sources.fetch_csv(FakeFetcher({}), self.URL, live=True), (None, None))

    def test_text_and_its_fetch_time_come_back(self):
        fetcher = FakeFetcher({self.URL: "a,b\n1,2\n"}, fetched_utc="2026-10-03T08:00:00Z")
        self.assertEqual(sources.fetch_csv(fetcher, self.URL, live=False), ("a,b\n1,2\n", "2026-10-03T08:00:00Z"))

    def test_a_live_file_may_be_refetched_and_an_old_one_never_is(self):
        fetcher = FakeFetcher({self.URL: "x\n"})
        sources.fetch_csv(fetcher, self.URL, live=True)
        sources.fetch_csv(fetcher, self.URL, live=False)
        self.assertEqual(fetcher.calls, [(self.URL, sources.LIVE_MAX_AGE_S), (self.URL, None)])

    def test_the_current_season_and_the_one_before_are_live_and_the_schedule_always_is(self):
        self.assertTrue(sources.is_live(None, 2026))
        self.assertTrue(sources.is_live(2026, 2026))
        self.assertTrue(sources.is_live(2025, 2026))
        self.assertFalse(sources.is_live(2024, 2026))

    def test_the_urls_are_nflverses_release_files(self):
        base = "https://github.com/nflverse/nflverse-data/releases/download"
        self.assertEqual(sources.games_url(), f"{base}/schedules/games.csv")
        self.assertEqual(sources.team_stats_url(2025), f"{base}/stats_team/stats_team_week_2025.csv")
        self.assertEqual(sources.player_stats_url(2024), f"{base}/stats_player/stats_player_week_2024.csv")
        self.assertEqual(sources.injuries_url(2026), f"{base}/injuries/injuries_2026.csv")


if __name__ == "__main__":
    unittest.main()
