"""src/pipeline/allsports_props_grade.py: grade_prop(row, box) against the data service's box scores.

Fixtures only: the trimmed real ESPN summaries in tests/fixtures/datasvc_espn (through the real parser, so the row
shape is the store's) and hand-built rows for the cases a trimmed fixture cannot show (a player who did not play,
a goalie, an anytime scorer, nflverse rows). No network, no store.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.datasvc.espn import parse
from src.pipeline.allsports_props_grade import (LOSS, PUSH, UNRESOLVED, VOID, WIN, grade_prop, grade_rows)

FIX = Path(__file__).parent / "fixtures" / "datasvc_espn"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def game_row(league="nba", *, completed=True, state="post", status="STATUS_FINAL", **extra):
    row = {"league": league, "game_id": "g1", "observed_utc": "2026-10-20T03:00:00Z", "date_utc": "2026-10-20T00:00:00Z",
           "state": state, "status": status, "completed": completed, "home_id": "19", "away_id": "29"}
    row.update(extra)
    return row


def prop(market, player, side="Over", line="10.5", sport="nba", **extra):
    row = {"event_id": "abc123", "market": market, "player": player, "side": side, "line": line, "price": -110,
           "book": "fanduel", "sport": sport, "observed_utc": "2026-10-20T22:00:00Z", "commence_time": "2026-10-21T00:00:00Z"}
    row.update(extra)
    return row


def espn_player(name, groups, *, pid="1", team="19", dnp=False, **extra):
    row = {"league": "nba", "game_id": "g1", "player_id": pid, "team_id": team, "player_name": name,
           "observed_utc": "2026-10-20T03:00:00Z", "stats": groups}
    if dnp:
        row["did_not_play"] = True
        row["dnp_reason"] = "COACH'S DECISION"
    row.update(extra)
    return row


def nba_line(points=0, rebounds=0, assists=0, threes_made=0, steals=0, blocks=0, turnovers=0, minutes="30"):
    return {"all": {"minutes": minutes, "points": str(points), "rebounds": str(rebounds), "assists": str(assists),
                    "steals": str(steals), "blocks": str(blocks), "turnovers": str(turnovers),
                    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": f"{threes_made}-6"}}


def box(players, game=None, **kw):
    return {"game": game or game_row(**kw), "team_games": [], "player_games": players}


class RealFixtureBox(unittest.TestCase):
    """The recorded NBA summary, parsed by the store's own parser, answers points and threes; the rest is honest."""

    @classmethod
    def setUpClass(cls):
        game = game_row(home_id="19", away_id="29", league="nba")
        cls.rows = parse.player_games(fx("nba_summary.json"), game, "2026-10-20T03:00:00Z")
        cls.box = {"game": game, "team_games": [], "player_games": cls.rows}

    def test_points_over_and_under_against_a_real_row(self):
        jjj = "Jaren Jackson Jr."                         # 30 points in the fixture
        self.assertEqual(grade_prop(prop("player_points", jjj, "Over", "28.5"), self.box)["status"], WIN)
        self.assertEqual(grade_prop(prop("player_points", jjj, "Under", "28.5"), self.box)["status"], LOSS)
        result = grade_prop(prop("player_points", jjj, "Over", "30"), self.box)
        self.assertEqual((result["status"], result["actual"], result["line"]), (PUSH, 30.0, 30.0))

    def test_threes_come_from_the_made_half_of_the_ratio(self):
        result = grade_prop(prop("player_threes", "Cedric Coward", "Over", "2.5"), self.box)    # 3-7 in the fixture
        self.assertEqual((result["status"], result["actual"]), (WIN, 3.0))

    def test_a_stat_the_trimmed_box_does_not_carry_is_unresolved_not_zero(self):
        result = grade_prop(prop("player_rebounds", "Cedric Coward", "Under", "9.5"), self.box)
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("cannot answer", result["reason"])

    def test_a_suffix_dropped_by_the_book_still_matches_through_the_name_rules_or_stays_unresolved(self):
        # "Jaren Jackson" for "Jaren Jackson Jr.": not an exact-enough name, never a void
        result = grade_prop(prop("player_points", "Jaren Jackson", "Over", "20.5"), self.box)
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("near", result["reason"])

    def test_the_matched_player_is_reported(self):
        result = grade_prop(prop("player_points", "Paolo Banchero", "Over", "24.5"), self.box)
        self.assertEqual(result["matched"]["name"], "Paolo Banchero")
        self.assertEqual(result["matched"]["player_id"], "4432573")


class DidNotPlayIsAVoid(unittest.TestCase):
    def test_a_row_marked_did_not_play(self):
        data = box([espn_player("Dru Smith", {"all": {}}, dnp=True), espn_player("Other Guy", nba_line(10), pid="2")])
        result = grade_prop(prop("player_points", "Dru Smith"), data)
        self.assertEqual(result["status"], VOID)
        self.assertIn("did not play", result["reason"])

    def test_zero_minutes_is_a_void_even_without_the_flag(self):
        data = box([espn_player("Dru Smith", nba_line(minutes="0")), espn_player("Other Guy", nba_line(10), pid="2")])
        self.assertEqual(grade_prop(prop("player_points", "Dru Smith"), data)["status"], VOID)

    def test_an_empty_stat_line_in_a_basketball_box_is_a_void(self):
        data = box([espn_player("Dru Smith", {"all": {}}), espn_player("Other Guy", nba_line(10), pid="2")])
        self.assertEqual(grade_prop(prop("player_points", "Dru Smith"), data)["status"], VOID)

    def test_an_inactive_player_the_box_does_not_list_is_a_void(self):
        data = box([espn_player("Other Guy", nba_line(10), pid="2")])
        result = grade_prop(prop("player_points", "Tyrese Haliburton"), data)
        self.assertEqual(result["status"], VOID)
        self.assertIn("not in the box score", result["reason"])

    def test_a_name_that_is_nearly_a_listed_player_is_not_voided(self):
        # "Nic Claxton" vs "Nicolas Claxton": a nickname is not a match (names.person_score), so unresolved, not void
        data = box([espn_player("Nicolas Claxton", nba_line(12), pid="9")])
        result = grade_prop(prop("player_points", "Nic Claxton"), data)
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("Nicolas Claxton", result["reason"])

    def test_a_player_who_played_is_graded_even_with_one_point(self):
        data = box([espn_player("Reserve Guy", nba_line(points=1, minutes="2"))])
        self.assertEqual(grade_prop(prop("player_points", "Reserve Guy", "Under", "0.5"), data)["status"], LOSS)

    def test_a_postponed_or_cancelled_game_voids_every_leg(self):
        for status in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            data = box([], game=game_row(completed=False, state="post", status=status))
            self.assertEqual(grade_prop(prop("player_points", "Anyone"), data)["status"], VOID, status)


class NeverAGuess(unittest.TestCase):
    def test_a_game_that_is_not_final_is_unresolved(self):
        data = box([espn_player("A B", nba_line(30))], completed=False, state="in", status="STATUS_IN_PROGRESS")
        self.assertEqual(grade_prop(prop("player_points", "A B"), data)["status"], UNRESOLVED)

    def test_no_box_a_bare_dict_and_an_unavailable_answer_are_unresolved(self):
        self.assertEqual(grade_prop(prop("player_points", "A B"), None)["status"], UNRESOLVED)
        self.assertEqual(grade_prop(prop("player_points", "A B"), {})["status"], UNRESOLVED)
        self.assertEqual(grade_prop(prop("player_points", "A B"), {"available": False, "missing": []})["status"],
                         UNRESOLVED)

    def test_a_box_with_no_game_record_cannot_be_shown_final(self):
        result = grade_prop(prop("player_points", "A B"), {"player_games": [espn_player("A B", nba_line(30))]})
        self.assertEqual(result["status"], UNRESOLVED)

    def test_a_box_with_no_player_lines_is_unresolved(self):
        result = grade_prop(prop("player_points", "A B"), box([]))
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("no player lines", result["reason"])

    def test_two_players_that_fit_the_name_are_ambiguous(self):
        data = box([espn_player("Jaylin Williams", nba_line(5), pid="1"),
                    espn_player("Jaylin Williams", nba_line(9), pid="2", team="29")])
        result = grade_prop(prop("player_points", "Jaylin Williams"), data)
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("ambiguous", result["reason"])

    def test_an_unknown_side_and_a_missing_line_are_unresolved(self):
        data = box([espn_player("A B", nba_line(30))])
        self.assertEqual(grade_prop(prop("player_points", "A B", side="Maybe"), data)["status"], UNRESOLVED)
        self.assertEqual(grade_prop(prop("player_points", "A B", line=None), data)["status"], UNRESOLVED)

    def test_a_yes_no_market_with_over_under_is_unresolved(self):
        data = box([espn_player("A B", nba_line(30))])
        self.assertEqual(grade_prop(prop("player_double_double", "A B", "Over", "0.5"), data)["status"], UNRESOLVED)

    def test_an_unknown_sport_and_a_market_nobody_grades_are_unresolved(self):
        data = box([espn_player("A B", nba_line(30))])
        self.assertEqual(grade_prop(prop("player_points", "A B", sport="cricket"), data)["status"], UNRESOLVED)
        self.assertEqual(grade_prop(prop("player_first_basket", "A B", "Yes", None), data)["status"], UNRESOLVED)

    def test_the_input_row_is_not_changed(self):
        data = box([espn_player("A B", nba_line(30))])
        row = prop("player_points", "A B")
        before = json.dumps(row, sort_keys=True), json.dumps(data, sort_keys=True)
        grade_prop(row, data)
        self.assertEqual((json.dumps(row, sort_keys=True), json.dumps(data, sort_keys=True)), before)


class BasketballMarkets(unittest.TestCase):
    def setUp(self):
        self.data = box([espn_player("Star Player", nba_line(points=28, rebounds=11, assists=9, threes_made=4,
                                                            steals=2, blocks=1, turnovers=3))])

    def status(self, market, side, line):
        return grade_prop(prop(market, "Star Player", side, line), self.data)["status"]

    def test_combined_markets_add_the_parts(self):
        self.assertEqual(self.status("player_points_rebounds_assists", "Over", "47.5"), WIN)      # 48
        self.assertEqual(self.status("player_points_rebounds_assists", "Over", "48"), PUSH)
        self.assertEqual(self.status("player_points_rebounds", "Under", "40.5"), WIN)             # 39
        self.assertEqual(self.status("player_points_assists", "Over", "36.5"), WIN)               # 37
        self.assertEqual(self.status("player_rebounds_assists", "Under", "19.5"), LOSS)           # 20
        self.assertEqual(self.status("player_blocks_steals", "Over", "2.5"), WIN)                 # 3

    def test_single_stats(self):
        self.assertEqual(self.status("player_assists", "Over", "8.5"), WIN)
        self.assertEqual(self.status("player_steals", "Under", "1.5"), LOSS)
        self.assertEqual(self.status("player_turnovers", "Over", "3.5"), LOSS)

    def test_double_double_and_triple_double_are_yes_no(self):
        self.assertEqual(self.status("player_double_double", "Yes", None), WIN)       # points, rebounds
        self.assertEqual(self.status("player_double_double", "No", None), LOSS)
        self.assertEqual(self.status("player_triple_double", "Yes", None), LOSS)      # assists 9
        self.assertEqual(self.status("player_triple_double", "No", None), WIN)


def hockey(name, group, **stats):
    base = {"timeOnIce": "18:00", "goals": "0", "assists": "0", "shotsTotal": "0", "blockedShots": "0"}
    base.update({k: str(v) for k, v in stats.items()})
    return espn_player(name, {group: base}, pid=name[:3], league="nhl")


class HockeyMarkets(unittest.TestCase):
    def setUp(self):
        goalie = espn_player("Sam Goalie", {"goalies": {"timeOnIce": "60:00", "saves": "27", "shotsAgainst": "29"}}, pid="g")
        self.data = box([hockey("Top Line", "forwards", goals=1, assists=1, shotsTotal=5, blockedShots=2),
                         hockey("Quiet Dman", "defenses"), goalie, hockey("Benched Guy", "forwards", timeOnIce="0:00")],
                        league="nhl")

    def grade(self, market, player, side, line, sport="nhl"):
        return grade_prop(prop(market, player, side, line, sport=sport), self.data)

    def test_points_are_goals_plus_assists(self):
        self.assertEqual(self.grade("player_points", "Top Line", "Over", "1.5")["status"], WIN)
        self.assertEqual(self.grade("player_points", "Quiet Dman", "Under", "0.5")["status"], WIN)

    def test_shots_blocks_and_saves(self):
        self.assertEqual(self.grade("player_shots_on_goal", "Top Line", "Over", "4.5")["status"], WIN)
        self.assertEqual(self.grade("player_blocked_shots", "Top Line", "Under", "1.5")["status"], LOSS)
        self.assertEqual(self.grade("player_total_saves", "Sam Goalie", "Over", "26.5")["status"], WIN)

    def test_saves_for_a_skater_is_unresolved(self):
        self.assertEqual(self.grade("player_total_saves", "Top Line", "Over", "20.5")["status"], UNRESOLVED)

    def test_anytime_scorer_yes_and_no(self):
        self.assertEqual(self.grade("player_goal_scorer_anytime", "Top Line", "Yes", None)["status"], WIN)
        self.assertEqual(self.grade("player_goal_scorer_anytime", "Top Line", "No", None)["status"], LOSS)
        self.assertEqual(self.grade("player_goal_scorer_anytime", "Quiet Dman", "Yes", None)["status"], LOSS)
        self.assertEqual(self.grade("player_goal_scorer_anytime", "Quiet Dman", "No", None)["status"], WIN)

    def test_a_skater_with_no_time_on_ice_did_not_play(self):
        self.assertEqual(self.grade("player_points", "Benched Guy", "Over", "0.5")["status"], VOID)

    def test_a_scratched_player_the_box_does_not_list_is_a_void(self):
        self.assertEqual(self.grade("player_shots_on_goal", "Healthy Scratch", "Over", "2.5")["status"], VOID)

    def test_power_play_points_cannot_be_answered(self):
        self.assertEqual(self.grade("player_power_play_points", "Top Line", "Over", "0.5")["status"], UNRESOLVED)


def nfl_row(name, **stats):
    row = {"game_id": "2026_07_DAL_PHI", "player_id": "00-" + name[:5], "name": name, "team": "DAL", "position": "WR",
           "season": 2026, "week": 7}
    row.update(stats)
    return row


class FootballMarkets(unittest.TestCase):
    def setUp(self):
        self.nfl = {"game": {"game_id": "2026_07_DAL_PHI", "status": "final"},
                    "player_games": [nfl_row("Dak Prescott", pass_attempts=34, completions=21, passing_yards=188,
                                             passing_tds=2, interceptions=1, carries=3, rushing_yards=8,
                                             rushing_tds=0, receptions=0, receiving_yards=0, receiving_tds=0),
                                     nfl_row("CeeDee Lamb", receptions=7, receiving_yards=102, receiving_tds=1,
                                             carries=0, rushing_yards=0, rushing_tds=0),
                                     nfl_row("Backup Rb", carries=4, rushing_yards=11, rushing_tds=0, receptions=1,
                                             receiving_yards=5, receiving_tds=0)]}

    def grade(self, market, player, side="Over", line="1.5"):
        return grade_prop(prop(market, player, side, line, sport="nfl"), self.nfl)

    def test_passing_rushing_and_receiving(self):
        self.assertEqual(self.grade("player_pass_yds", "Dak Prescott", "Under", "225.5")["status"], WIN)
        self.assertEqual(self.grade("player_pass_tds", "Dak Prescott", "Over", "1.5")["status"], WIN)
        self.assertEqual(self.grade("player_pass_attempts", "Dak Prescott", "Over", "34")["status"], PUSH)
        self.assertEqual(self.grade("player_pass_completions", "Dak Prescott", "Over", "21.5")["status"], LOSS)
        self.assertEqual(self.grade("player_pass_interceptions", "Dak Prescott", "Over", "0.5")["status"], WIN)
        self.assertEqual(self.grade("player_reception_yds", "CeeDee Lamb", "Over", "89.5")["status"], WIN)
        self.assertEqual(self.grade("player_receptions", "CeeDee Lamb", "Under", "7.5")["status"], WIN)
        self.assertEqual(self.grade("player_rush_yds", "Backup Rb", "Over", "10.5")["status"], WIN)
        self.assertEqual(self.grade("player_rush_reception_yds", "Backup Rb", "Under", "20.5")["status"], WIN)

    def test_anytime_td_counts_rushing_and_receiving_and_says_what_it_leaves_out(self):
        won = self.grade("player_anytime_td", "CeeDee Lamb", "Yes", None)
        self.assertEqual(won["status"], WIN)
        self.assertIn("return and defensive", won["note"])
        self.assertEqual(self.grade("player_anytime_td", "Backup Rb", "Yes", None)["status"], LOSS)
        self.assertEqual(self.grade("player_anytime_td", "Backup Rb", "No", None)["status"], WIN)

    def test_a_player_with_no_nflverse_row_is_unresolved_not_a_void_or_a_zero(self):
        result = self.grade("player_receptions", "Nobody Here", "Under", "0.5")
        self.assertEqual(result["status"], UNRESOLVED)

    def test_a_game_the_schedule_file_has_not_finalised_is_unresolved(self):
        self.nfl["game"]["status"] = "in_progress"
        self.assertEqual(self.grade("player_pass_yds", "Dak Prescott", "Under", "225.5")["status"], UNRESOLVED)

    def test_college_football_from_the_espn_fixture(self):
        game = game_row("ncaaf")
        rows = parse.player_games(fx("ncaaf_summary.json"), game, "2026-10-20T03:00:00Z")
        data = {"game": game, "player_games": rows}

        def g(market, player, side, line):
            return grade_prop(prop(market, player, side, line, sport="ncaaf"), data)

        self.assertEqual(g("player_pass_yds", "Luke Duncan", "Under", "170.5")["status"], WIN)          # 154
        self.assertEqual(g("player_rush_yds", "Bo Jackson", "Over", "99.5")["status"], WIN)             # 112
        self.assertEqual(g("player_reception_yds", "Rico Flores Jr.", "Over", "58.5")["status"], WIN)   # 59
        self.assertEqual(g("player_receptions", "Jeremiah Smith", "Over", "3.5")["status"], WIN)        # 4
        # the trimmed fixture has no touchdown columns: unresolved, never "no touchdown"
        self.assertEqual(g("player_anytime_td", "Bo Jackson", "Yes", None)["status"], UNRESOLVED)
        # a player the football box does not list may simply have no stat yet: unresolved, never a void
        self.assertEqual(g("player_rush_yds", "Not Listed", "Over", "5.5")["status"], UNRESOLVED)

    def test_college_football_with_no_player_lines_is_unresolved(self):
        data = {"game": game_row("ncaaf"), "team_games": [], "player_games": []}
        result = grade_prop(prop("player_pass_yds", "Luke Duncan", "Over", "200.5", sport="ncaaf"), data)
        self.assertEqual(result["status"], UNRESOLVED)
        self.assertIn("no player lines", result["reason"])


class AWholeServiceAnswerIsAccepted(unittest.TestCase):
    def test_available_true_wraps_the_data(self):
        answer = {"available": True, "sport": "nba", "kind": "game", "data": box([espn_player("A B", nba_line(30))]),
                  "meta": {}}
        self.assertEqual(grade_prop(prop("player_points", "A B", "Over", "25.5"), answer)["status"], WIN)

    def test_grade_rows_marks_a_row_without_a_box_unresolved(self):
        rows = [prop("player_points", "A B", "Over", "25.5"), prop("player_points", "A B", "Over", "35.5")]
        got = grade_rows(rows, lambda r: box([espn_player("A B", nba_line(30))]) if r["line"] == "25.5" else None)
        self.assertEqual([g["status"] for g in got], [WIN, UNRESOLVED])


if __name__ == "__main__":
    unittest.main()
