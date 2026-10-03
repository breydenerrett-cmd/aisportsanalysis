"""src/situation/mlb.py: `situation_for_game`, checked on the hand-built world in
tests/situation_fixtures.py (every figure there can be verified on paper)."""

from __future__ import annotations

import copy
import math
import random
import unittest

from src.situation import mlb
from src.situation import record as rec
from tests import situation_fixtures as F


def by_key(record):
    return {(f["family"], f["name"], f["side"]): f for f in record["factors"]}


def gaps_of(record):
    return {(g["family"], g["name"], g["side"]): g["reason"] for g in record["missing"]}


def run(game, rows=None, **kw):
    return mlb.situation_for_game(game, F.world() if rows is None else rows, strict=True, **kw)


def haversine_miles(a, b):
    """An independent great-circle distance (R = 3958.8 miles) to check the park-to-park figure."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


class ARegularSeasonGame(unittest.TestCase):
    """BOS at NYY on 2025-09-28. NYY played 12 straight days ending 09-25; BOS ended 09-27 at TB."""

    @classmethod
    def setUpClass(cls):
        cls.r = run(F.regular_game())
        cls.f = by_key(cls.r)
        cls.gaps = gaps_of(cls.r)

    def v(self, family, name, side):
        return self.f[(family, name, side)]

    def test_the_record_is_sound_and_says_what_it_is(self):
        self.assertEqual(rec.problems(self.r), [])
        self.assertEqual(self.r["sport"], "mlb")
        self.assertEqual(self.r["as_of"], "2025-09-28")
        self.assertEqual(self.r["subject"]["away"], "BOS")
        self.assertEqual(self.r["coverage"]["results_store_starts"], "2025-08-10")
        self.assertTrue(self.r["coverage"]["results_current"])

    # -- rest and rhythm ---------------------------------------------------------------

    def test_days_since_each_clubs_last_game(self):
        nyy = self.v("rest_and_rhythm", "days_since_last_game", "home")
        bos = self.v("rest_and_rhythm", "days_since_last_game", "away")
        self.assertEqual((nyy["value"], nyy["as_of"], nyy["detail"]["days_off"]), (3, "2025-09-25", 2))
        self.assertEqual(nyy["sentence"], "NYY last played 3 days earlier (2025-09-25), 2 days off.")
        self.assertEqual((bos["value"], bos["as_of"]), (1, "2025-09-27"))
        self.assertEqual(bos["sentence"], "BOS played yesterday (2025-09-27).")

    def test_games_in_the_last_seven_days_include_the_seventh_day_back(self):
        # 09-28 minus 7 days is 09-21: d8 to d12 are five games; BOS played 09-26 and 09-27
        self.assertEqual(self.v("rest_and_rhythm", "games_last_7_days", "home")["value"], 5)
        self.assertEqual(self.v("rest_and_rhythm", "games_last_7_days", "away")["value"], 2)
        self.assertEqual(self.v("rest_and_rhythm", "games_last_7_days", "home")["sentence"],
                         "NYY played 5 games in the last 7 days.")

    def test_travel_is_the_distance_from_the_park_of_the_last_game(self):
        nyy = self.v("rest_and_rhythm", "travel_miles", "home")
        bos = self.v("rest_and_rhythm", "travel_miles", "away")
        self.assertEqual(nyy["value"], 0)
        self.assertEqual(nyy["sentence"], "NYY did not travel: it last played at Yankee Stadium, the same park.")
        tb, nyc = (27.7683, -82.6534), (40.8296, -73.9262)       # Tropicana Field to Yankee Stadium
        self.assertAlmostEqual(bos["value"], haversine_miles(tb, nyc), delta=0.6)      # "about" N miles
        self.assertTrue(1000 <= bos["value"] <= 1040)
        self.assertEqual(bos["sentence"],
                         f"BOS travels about {bos['value']} miles from where it last played (Tropicana Field).")

    # -- form --------------------------------------------------------------------------

    def test_nyy_last_five_and_last_ten_are_the_hand_checked_figures(self):
        five = self.v("form", "last_5", "home")
        self.assertEqual(five["value"], 4)
        self.assertEqual(five["detail"], {"games": 5, "wins": 4, "losses": 1, "run_margin": 5,
                                          "run_margin_per_game": 1.0, "runs_for": 18, "runs_against": 13})
        self.assertEqual(five["sentence"],
                         "NYY is 4-1 over its last 5 games, outscoring opponents by 5 runs in total (1.0 a game).")
        ten = self.v("form", "last_10", "home")
        self.assertEqual(ten["value"], 7)
        self.assertEqual((ten["detail"]["runs_for"], ten["detail"]["runs_against"], ten["detail"]["run_margin"]),
                         (38, 28, 10))
        self.assertEqual(ten["sample"], {"games": 10, "window": 10})

    def test_a_club_with_fewer_games_than_the_window_says_so(self):
        ten = self.v("form", "last_10", "away")        # BOS has five games this season in the data
        self.assertEqual(ten["detail"]["games"], 5)
        self.assertEqual(ten["detail"]["wins"], 3)
        self.assertEqual(ten["detail"]["run_margin"], 5)
        self.assertIn("its only 5 games this season", ten["sentence"])
        self.assertEqual(ten["sample"], {"games": 5, "window": 10})

    def test_the_streak(self):
        nyy = self.v("form", "streak", "home")
        self.assertEqual((nyy["value"], nyy["detail"]["type"]), (1, "loss"))
        self.assertEqual(nyy["sentence"], "NYY lost its last game.")
        self.assertEqual(self.v("form", "streak", "away")["detail"]["type"], "loss")

    def test_runs_a_game_recently_against_the_season(self):
        nyy = self.v("form", "runs_per_game_recent_vs_season", "home")
        self.assertEqual(nyy["value"], 3.8)                         # 38 runs over the last 10
        self.assertEqual(nyy["detail"]["season_games"], 15)         # 12 in September and 3 in August
        self.assertAlmostEqual(nyy["detail"]["season_runs_per_game"], 50 / 15, places=3)
        self.assertEqual(nyy["sentence"],
                         "NYY scored 3.8 runs a game over its last 10, against 3.3 over its 15 regular-season games.")

    def test_when_the_recent_games_are_the_whole_season_there_is_nothing_to_compare(self):
        self.assertIn(("form", "runs_per_game_recent_vs_season", "away"), self.gaps)
        self.assertNotIn(("form", "runs_per_game_recent_vs_season", "away"), self.f)

    # -- stakes and pressure -----------------------------------------------------------

    def test_a_regular_season_game_has_no_series_and_says_the_race_is_not_stated(self):
        self.assertNotIn(("stakes", "series_state", "game"), self.f)
        self.assertIn(("stakes", "playoff_race", "game"), self.gaps)

    def test_the_postseason_families_are_written_for_postseason_games_only(self):
        for key in (("stakes", "series_wins_in_data", "home"), ("pressure_history", "postseason_record", "home"),
                    ("stakes", "series_state", "game")):
            self.assertNotIn(key, self.f)
        self.assertNotIn(("pressure_history", "manager_record", "game"), self.gaps)

    # -- head to head ------------------------------------------------------------------

    def test_this_seasons_series_is_counted_from_the_away_clubs_side(self):
        s = self.v("head_to_head", "season_series", "game")
        self.assertEqual((s["value"], s["detail"]), (3, {"away_wins": 2, "home_wins": 1}))
        self.assertEqual(s["sentence"], "This season BOS is 2-1 against NYY in 3 games.")

    def test_the_last_meetings_are_newest_first(self):
        m = self.v("head_to_head", "last_meetings", "game")
        self.assertEqual(m["value"], 3)
        self.assertEqual([x["date"] for x in m["detail"]["meetings"]], ["2025-08-12", "2025-08-11", "2025-08-10"])
        self.assertEqual([x["winner"] for x in m["detail"]["meetings"]], ["BOS", "NYY", "BOS"])
        self.assertEqual(m["sentence"], "The last 3 meetings in our data: BOS won 4-0 on 2025-08-12; "
                                        "NYY won 3-2 on 2025-08-11; BOS won 5-1 on 2025-08-10.")

    # -- availability ------------------------------------------------------------------

    def test_a_probable_starters_rest_counts_his_listed_starts_this_season(self):
        # Schmidt started d3 (09-16), d8 (09-21) and 08-12; the last was 7 days before 09-28
        s = self.v("availability", "probable_rest", "home")
        self.assertEqual((s["value"], s["detail"]["days_of_rest"], s["detail"]["starts_last_30_days"]), (7, 6, 2))
        self.assertEqual(s["sample"], {"starts_this_season": 3})
        self.assertEqual(s["sentence"], "Marcus Schmidt last started 7 days earlier (2025-09-21), 6 days of rest.")
        b = self.v("availability", "probable_rest", "away")      # Bello: 08-11 and 09-26
        self.assertEqual((b["value"], b["detail"]["days_of_rest"], b["detail"]["starts_last_30_days"]), (2, 1, 1))
        self.assertEqual(b["sentence"], "Brayan Bello last started 2 days earlier (2025-09-26), 1 day of rest.")

    def test_there_is_no_previous_round_in_the_regular_season(self):
        self.assertNotIn(("availability", "starters_previous_round", "home"), self.f)
        self.assertNotIn(("rest_and_rhythm", "previous_round", "home"), self.f)

    # -- venue -------------------------------------------------------------------------

    def test_the_park_and_its_roof(self):
        self.assertEqual(self.v("venue", "park", "game")["value"], "Yankee Stadium")
        self.assertEqual(self.v("venue", "park", "game")["sentence"], "NYY host at Yankee Stadium.")
        self.assertEqual(self.v("venue", "roof", "game")["value"], "open")
        self.assertEqual(self.v("venue", "roof", "game")["sentence"], "Yankee Stadium is an open-air park.")

    def test_the_page_block_for_a_regular_season_game(self):
        shown = [(self.r["factors"][i]["name"], self.r["factors"][i]["side"]) for i in self.r["display"]]
        self.assertEqual(shown, [("days_since_last_game", "away"), ("days_since_last_game", "home"),
                                 ("last_10", "away"), ("last_10", "home"), ("season_series", "game")])


class ADivisionSeriesOpener(unittest.TestCase):
    """Game 1, 2025-10-04, TB at NYY: NYY had a bye, TB came through the Wild Card Series."""

    @classmethod
    def setUpClass(cls):
        cls.r = run(F.division_game(1))
        cls.f = by_key(cls.r)

    def test_the_bye_and_the_club_that_played(self):
        nyy, tb = self.f[("rest_and_rhythm", "previous_round", "home")], self.f[("rest_and_rhythm", "previous_round", "away")]
        self.assertEqual(nyy["value"], "bye")
        self.assertEqual(nyy["sentence"], "NYY had a bye: it did not play in the Wild Card Series.")
        self.assertEqual(tb["value"], "played")
        self.assertEqual(tb["sentence"], "TB won the Wild Card Series 2-1 over BOS (3 games), which ended "
                                         "2025-10-02, 2 days earlier.")
        self.assertEqual(tb["detail"], {"round": "Wild Card Series", "opponent": "BOS", "wins": 2, "losses": 1,
                                        "games": 3, "ended": "2025-10-02", "days_since_ended": 2, "won": True})

    def test_rest_since_the_last_game_differs_by_a_week(self):
        nyy = self.f[("rest_and_rhythm", "days_since_last_game", "home")]
        tb = self.f[("rest_and_rhythm", "days_since_last_game", "away")]
        self.assertEqual((nyy["value"], tb["value"]), (9, 2))        # 09-25 and 10-02
        self.assertEqual(nyy["sentence"], "NYY last played 9 days earlier (2025-09-25), 8 days off.")
        self.assertEqual(tb["sentence"], "TB had a day off: it last played on 2025-10-02, 2 days earlier.")

    def test_tb_travels_from_its_own_park_to_new_york(self):
        tb = self.f[("rest_and_rhythm", "travel_miles", "away")]
        self.assertTrue(1000 <= tb["value"] <= 1040)

    def test_game_one_of_a_best_of_five(self):
        s = self.f[("stakes", "series_state", "game")]
        self.assertEqual(s["value"], 1)
        self.assertEqual(s["sentence"], "Game 1 of the Division Series (best of 5).")
        self.assertEqual(s["detail"], {"round": "Division Series", "best_of": 5, "wins_needed": 3,
                                       "away_wins": 0, "home_wins": 0})
        self.assertEqual(s["sample"], {"games_played": 0})

    def test_nobody_faces_elimination_in_game_one(self):
        for side in ("away", "home"):
            self.assertIs(self.f[("stakes", "elimination", side)]["value"], False)
        shown = [(self.r["factors"][i]["name"], self.r["factors"][i]["side"]) for i in self.r["display"]]
        self.assertNotIn(("elimination", "away"), shown)       # "not facing elimination" is not news

    def test_who_started_the_round_before(self):
        tb = self.f[("availability", "starters_previous_round", "away")]
        self.assertEqual(tb["value"], 3)
        self.assertEqual(tb["sentence"], "TB's listed starters in the Wild Card Series: game 1 Drew Rasmussen, "
                                         "game 2 Ryan Pepiot, game 3 Shane McClanahan.")
        self.assertEqual([s["starter"] for s in tb["detail"]["starters"]],
                         ["Drew Rasmussen", "Ryan Pepiot", "Shane McClanahan"])
        self.assertNotIn(("availability", "starters_previous_round", "home"), self.f)       # a bye: none

    def test_a_probable_who_started_in_the_previous_round_says_so(self):
        tb = self.f[("availability", "probable_rest", "away")]            # Drew Rasmussen, WC game 1 on 09-30
        self.assertEqual((tb["value"], tb["detail"]["days_of_rest"]), (4, 3))
        self.assertIn("in the Wild Card Series", tb["sentence"])
        self.assertIs(tb["detail"]["last_start_postseason"], True)

    def test_a_club_that_won_a_series_has_won_one_and_the_other_has_not(self):
        tb = self.f[("stakes", "series_wins_in_data", "away")]
        nyy = self.f[("stakes", "series_wins_in_data", "home")]
        self.assertEqual((tb["value"], nyy["value"]), (1, 0))
        self.assertEqual(tb["detail"], {"first_season_in_data": 2025, "last_series_win_season": 2025,
                                        "last_series_win_round": "Wild Card Series"})
        self.assertEqual(tb["sentence"], "TB has won 1 postseason series in our data (2025 on), most recently in 2025.")

    def test_a_drought_is_only_stated_as_far_back_as_the_data_and_the_record_says_so(self):
        gap = gaps_of(self.r)[("stakes", "milestone_before_data", "game")]
        self.assertIn("only stated back to 2025", gap)
        older = run(F.division_game(1), extra_games=[F.g(9001, "2019-10-04", "TB", "HOU", 4, 1, "D")])
        self.assertIn("only stated back to 2019", gaps_of(older)[("stakes", "milestone_before_data", "game")])

    def test_a_regular_season_game_makes_no_milestone_claim(self):
        self.assertNotIn(("stakes", "milestone_before_data", "game"), gaps_of(run(F.regular_game())))

    def test_pressure_history_sets_the_postseason_against_the_regular_season(self):
        tb = self.f[("pressure_history", "postseason_record", "away")]
        self.assertEqual(tb["value"], 3)
        d = tb["detail"]
        self.assertEqual((d["wins"], d["losses"], d["series_won"], d["series_lost"]), (2, 1, 1, 0))
        # TB's 2025 regular season in the data: 4 wins in the 12 at NYY, a loss and a win against BOS = 5-9
        self.assertEqual((d["regular_season_games"], d["regular_season_win_pct"]), (14, round(5 / 14, 4)))
        self.assertEqual(d["win_pct"], round(2 / 3, 4))
        self.assertEqual(d["win_pct_difference"], round(2 / 3 - 5 / 14, 4))
        self.assertEqual(tb["sentence"], "TB is 2-1 in 3 postseason games in our data (2025 on), 1-0 in series, "
                                         "a 67% win rate, against 36% in the regular seasons it reached the "
                                         "postseason (14 games).")
        self.assertEqual(self.f[("pressure_history", "postseason_record", "home")]["value"], 0)

    def test_the_page_block_leads_with_the_series_and_the_rest_picture(self):
        shown = [(self.r["factors"][i]["name"], self.r["factors"][i]["side"]) for i in self.r["display"]]
        self.assertEqual(shown[:3], [("series_state", "game"), ("previous_round", "away"), ("previous_round", "home")])


class TheRestOfTheSeries(unittest.TestCase):
    def test_game_three_is_a_tied_series_and_the_home_club_is_tb(self):
        r = run(F.division_game(3))
        f = by_key(r)
        s = f[("stakes", "series_state", "game")]
        self.assertEqual(s["value"], 3)
        self.assertEqual(s["sentence"], "Game 3 of the Division Series (best of 5): the series is tied 1-1.")
        self.assertEqual((s["detail"]["away_wins"], s["detail"]["home_wins"]), (1, 1))   # away is NYY, home TB
        self.assertEqual(r["subject"]["away"], "NYY")

    def test_game_four_has_the_home_club_one_loss_from_elimination(self):
        r = run(F.division_game(4))
        f = by_key(r)
        self.assertEqual(f[("stakes", "series_state", "game")]["sentence"],
                         "Game 4 of the Division Series (best of 5): NYY lead 2-1.")
        self.assertIs(f[("stakes", "elimination", "home")]["value"], True)       # TB
        self.assertIs(f[("stakes", "elimination", "away")]["value"], False)      # NYY
        self.assertEqual(f[("stakes", "elimination", "home")]["sentence"], "TB faces elimination: NYY need one more win.")
        self.assertEqual(f[("stakes", "elimination", "home")]["detail"],
                         {"own_wins": 1, "opponent_wins": 2, "wins_needed": 3})
        shown = [(r["factors"][i]["name"], r["factors"][i]["side"]) for i in r["display"]]
        self.assertIn(("elimination", "home"), shown)       # elimination is news when it is true

    def test_game_five_has_both_clubs_one_loss_from_elimination(self):
        f = by_key(run(F.division_game(5)))
        self.assertEqual(f[("stakes", "series_state", "game")]["sentence"],
                         "Game 5 of the Division Series (best of 5): the series is tied 2-2.")
        self.assertIs(f[("stakes", "elimination", "home")]["value"], True)
        self.assertIs(f[("stakes", "elimination", "away")]["value"], True)

    def test_the_head_to_head_inside_a_series_counts_the_series_games_too(self):
        f = by_key(run(F.division_game(4)))
        s = f[("head_to_head", "season_series", "game")]
        # twelve September games (NYY 8-4) and the three series games before this one (NYY won G1 and G3)
        self.assertEqual(s["value"], 15)
        self.assertEqual(s["sentence"], "This season NYY is 10-5 against TB in 15 games.")

    def test_the_series_score_is_the_score_going_into_the_game_not_after(self):
        # game 1 never sees its own result: it is Game 1 with nobody ahead
        f = by_key(run(F.division_game(1)))
        self.assertEqual(f[("stakes", "series_state", "game")]["detail"]["home_wins"], 0)

    def test_a_league_championship_game_reads_the_division_series_the_clubs_came_through(self):
        game = F.game(501, "2025-10-12", "TOR", "NYY", "L", venue="Yankee Stadium")
        r = run(game)
        f = by_key(r)
        nyy = f[("rest_and_rhythm", "previous_round", "home")]
        self.assertEqual(nyy["sentence"], "NYY won the Division Series 3-2 over TB (5 games), which ended "
                                          "2025-10-09, 3 days earlier.")
        # TOR won the Wild Card Series and has no Division Series in the data: the store cannot say
        self.assertNotIn(("rest_and_rhythm", "previous_round", "away"), f)
        self.assertIn(("rest_and_rhythm", "previous_round", "away"), gaps_of(r))
        self.assertEqual(f[("stakes", "series_state", "game")]["detail"]["best_of"], 7)
        self.assertEqual(f[("stakes", "series_wins_in_data", "home")]["value"], 1)

    def test_a_decided_series_is_not_read_as_open(self):
        # a sixth game that cannot exist: the data already shows the series decided
        game = F.game(406, "2025-10-10", "TB", "NYY", "D", venue="Yankee Stadium")
        r = run(game)
        self.assertNotIn(("stakes", "series_state", "game"), by_key(r))
        self.assertIn(("stakes", "series_state", "game"), gaps_of(r))


class TheWildCardGate(unittest.TestCase):
    def test_a_missing_wild_card_round_leaves_the_bye_unknown_and_says_so(self):
        rows = [r for r in F.world() if r["game_type"] != "F"]
        # the manifest confirms the days between the last regular-season game and this one, so the
        # store is current and the only thing missing is the round itself
        covered = [f"2025-09-{d}" for d in (28, 29, 30)] + [f"2025-10-0{d}" for d in (1, 2, 3)]
        r = run(F.division_game(1), rows, covered_dates=covered)
        gaps = gaps_of(r)
        for side in ("away", "home"):
            self.assertIn(("rest_and_rhythm", "previous_round", side), gaps)
            self.assertNotIn(("rest_and_rhythm", "previous_round", side), by_key(r))
        self.assertIn("not fully in the data", gaps[("rest_and_rhythm", "previous_round", "home")])


class PointInTime(unittest.TestCase):
    """A game on the as-of date and later never counts: the record built from the whole world
    equals the one built from the world as it was the day before."""

    GAMES = [("regular", F.regular_game), ("DS1", lambda: F.division_game(1)), ("DS3", lambda: F.division_game(3)),
             ("DS4", lambda: F.division_game(4)), ("DS5", lambda: F.division_game(5))]

    def test_the_whole_world_and_the_world_as_it_was_give_the_same_record(self):
        rows = F.world()
        for label, make_game in self.GAMES:
            game = make_game()
            before = [r for r in rows if r["date"] < game["date"]]
            self.assertEqual(run(game, rows), run(game, before), label)

    def test_a_game_on_the_date_changes_nothing_even_between_the_same_clubs(self):
        game = F.regular_game()
        baseline = run(game)
        absurd = F.g(999, "2025-09-28", "BOS", "NYY", 40, 0, away_probable="Brayan Bello", away_probable_id=11,
                     home_probable="Marcus Schmidt", home_probable_id=3)       # the first half of a doubleheader
        later = F.g(998, "2025-09-29", "BOS", "NYY", 0, 40)
        self.assertEqual(run(game, F.world() + [absurd, later]), baseline)

    def test_the_game_itself_with_its_result_is_not_read(self):
        game = F.division_game(2)
        with_itself = run(game, F.world())
        without = run(game, [r for r in F.world() if r["game_pk"] != "402"])
        self.assertEqual(with_itself, without)

    def test_every_factor_is_stamped_before_the_game_date(self):
        for _label, make_game in self.GAMES:
            game = make_game()
            r = run(game)
            self.assertEqual(rec.problems(r), [])
            for f in r["factors"]:
                self.assertLess(f["as_of"], game["date"], f"{f['family']}.{f['name']}")

    def test_the_order_of_the_rows_does_not_matter(self):
        rows = F.world()
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        for _label, make_game in self.GAMES:
            self.assertEqual(run(make_game(), rows), run(make_game(), shuffled))

    def test_the_rows_are_not_modified(self):
        rows = F.world()
        frozen = copy.deepcopy(rows)
        run(F.division_game(4), rows)
        self.assertEqual(rows, frozen)


class AStaleStore(unittest.TestCase):
    def game(self):
        return F.game(601, "2025-10-20", "NYY", "TB", "L", venue="Tropicana Field")

    def test_without_a_manifest_a_gap_of_more_than_three_days_is_stale(self):
        r = run(self.game())
        names = {(f["family"], f["name"]) for f in r["factors"]}
        for left_out in (("rest_and_rhythm", "days_since_last_game"), ("form", "last_10"),
                         ("availability", "probable_rest"), ("stakes", "series_state"),
                         ("rest_and_rhythm", "previous_round")):
            self.assertNotIn(left_out, names)
        self.assertIn(("rest_and_rhythm", "results_store_current", "game"), gaps_of(r))
        self.assertFalse(r["coverage"]["results_current"])
        self.assertIn("2025-10-09", gaps_of(r)[("rest_and_rhythm", "results_store_current", "game")])

    def test_the_long_memory_facts_survive_a_stale_store(self):
        r = run(self.game())
        names = {(f["family"], f["name"]) for f in r["factors"]}
        for kept in (("pressure_history", "postseason_record"), ("head_to_head", "season_series"),
                     ("venue", "park"), ("stakes", "series_wins_in_data")):
            self.assertIn(kept, names)

    def test_a_manifest_that_confirms_every_day_makes_a_long_break_current(self):
        covered = [f"2025-10-{d:02d}" for d in range(10, 20)]
        r = run(self.game(), covered_dates=covered)
        self.assertTrue(r["coverage"]["results_current"])
        self.assertIn(("rest_and_rhythm", "days_since_last_game", "home"), by_key(r))

    def test_a_manifest_missing_a_day_names_it(self):
        covered = [f"2025-10-{d:02d}" for d in range(10, 20) if d != 15]
        r = run(self.game(), covered_dates=covered)
        self.assertFalse(r["coverage"]["results_current"])
        self.assertIn("2025-10-15", gaps_of(r)[("rest_and_rhythm", "results_store_current", "game")])

    def test_a_three_day_gap_with_no_manifest_is_still_current(self):
        # the first game after a three-day league break is not stale: the break is real
        r = run(F.game(602, "2025-10-12", "TOR", "NYY", "L", venue="Yankee Stadium"))
        self.assertTrue(r["coverage"]["results_current"])

    def test_a_store_with_nothing_before_the_game_is_stale_and_says_so(self):
        r = run(F.regular_game(), [])
        self.assertEqual(r["factors"][0]["family"], "venue")
        self.assertFalse(r["coverage"]["results_current"])


class ADoubleheader(unittest.TestCase):
    def test_the_second_game_leaves_the_day_counts_out_and_says_why(self):
        game = F.regular_game()
        game.update(double_header="Y", game_number=2)
        r = run(game)
        f, gaps = by_key(r), gaps_of(r)
        self.assertIn(("rest_and_rhythm", "earlier_game_today", "game"), gaps)
        for side in ("away", "home"):
            self.assertNotIn(("rest_and_rhythm", "days_since_last_game", side), f)
        self.assertIn(("form", "last_10", "home"), f)       # form still runs through yesterday

    def test_the_first_game_reads_as_a_normal_game(self):
        game = F.regular_game()
        game.update(double_header="Y", game_number=1)
        self.assertIn(("rest_and_rhythm", "days_since_last_game", "home"), by_key(run(game)))


class WhenTheDataCannotSay(unittest.TestCase):
    def test_an_opener_has_no_days_since(self):
        r = run(F.game(1, "2025-04-01", "BOS", "NYY"), [F.g(2, "2025-03-30", "TB", "TOR", 1, 0)])
        self.assertIn(("rest_and_rhythm", "days_since_last_game", "home"), gaps_of(r))
        self.assertIn(("form", "last_10", "away"), gaps_of(r))

    def test_no_probable_starter_is_a_gap(self):
        game = F.regular_game()
        game.update(away_probable=None, away_probable_id=None)
        self.assertIn(("availability", "probable_rest", "away"), gaps_of(run(game)))

    def test_a_probable_with_no_earlier_start_is_a_gap(self):
        game = F.regular_game()
        game.update(away_probable="Nobody Known", away_probable_id=1234)
        reason = gaps_of(run(game))[("availability", "probable_rest", "away")]
        self.assertIn("no earlier start", reason)

    def test_an_unknown_park_is_a_gap_not_an_error(self):
        game = F.game(1, "2025-09-28", "BOS", "XXX")
        self.assertIn(("venue", "park", "game"), gaps_of(run(game)))

    def test_a_game_with_no_date_or_one_club_is_refused(self):
        with self.assertRaises(ValueError):
            mlb.situation_for_game({"away_team": "BOS", "home_team": "NYY"}, F.world())
        with self.assertRaises(ValueError):
            mlb.situation_for_game(F.game(1, "2025-09-28", "NYY", "NYY"), F.world())

    def test_a_family_that_fails_is_listed_not_raised(self):
        from unittest import mock
        with mock.patch.object(mlb, "_form", side_effect=RuntimeError("boom")):
            r = mlb.situation_for_game(F.regular_game(), F.world())       # strict is off in production
        self.assertTrue(any(g["family"] == "form" and "RuntimeError" in g["reason"] for g in r["missing"]))
        self.assertTrue(any(f["family"] == "venue" for f in r["factors"]))

    def test_unknown_game_types_are_ignored(self):
        junk = F.g(77, "2025-09-27", "BOS", "NYY", 30, 0, "S")        # spring training
        base = run(F.regular_game())
        self.assertEqual(run(F.regular_game(), F.world() + [junk]), base)


class TheLongerHistory(unittest.TestCase):
    """Earlier postseasons from the display-only store extend the long-memory facts only."""

    def history(self):
        return [F.g(9001, "2019-10-04", "TB", "HOU", 4, 1, "D"), F.g(9002, "2019-10-05", "TB", "HOU", 2, 6, "D"),
                F.g(9003, "2019-10-07", "HOU", "TB", 3, 1, "D"), F.g(9004, "2019-10-08", "HOU", "TB", 1, 4, "D"),
                F.g(9005, "2019-10-10", "TB", "HOU", 4, 6, "D")]

    def test_a_drought_is_stated_only_as_far_back_as_the_data_goes(self):
        r = run(F.division_game(1), extra_games=self.history())
        f = by_key(r)
        tb = f[("stakes", "series_wins_in_data", "away")]
        self.assertEqual(tb["detail"]["first_season_in_data"], 2019)
        # the 2019 Division Series was lost (TB 2-3), the 2025 Wild Card Series won
        self.assertEqual(tb["value"], 1)
        self.assertEqual(f[("pressure_history", "postseason_record", "away")]["detail"]["seasons"], [2019, 2025])

    def test_a_regular_season_the_store_does_not_hold_comes_from_the_supplied_records(self):
        records = {(2019, "TB"): {"wins": 96, "losses": 66}}
        r = run(F.division_game(1), extra_games=self.history(), season_records=records)
        d = by_key(r)[("pressure_history", "postseason_record", "away")]["detail"]
        self.assertEqual(d["regular_season_games"], 14 + 162)
        self.assertEqual(d["regular_season_win_pct"], round((5 + 96) / (14 + 162), 4))
        self.assertNotIn(("pressure_history", "regular_season_win_rate", "away"), gaps_of(r))

    def test_without_those_records_the_season_is_left_out_of_the_comparison_and_listed(self):
        r = run(F.division_game(1), extra_games=self.history())
        d = by_key(r)[("pressure_history", "postseason_record", "away")]["detail"]
        self.assertEqual(d["regular_season_games"], 14)           # 2025 only
        reason = gaps_of(r)[("pressure_history", "regular_season_win_rate", "away")]
        self.assertIn("2019", reason)

    def test_the_standings_beat_the_rows_for_a_regular_season_record(self):
        """The standings count every game, including the opening series abroad that the results store
        starts after (LAD and CHC in 2025 differ by two games), so they are the authority."""
        records = {(2025, "TB"): {"wins": 100, "losses": 62}}
        d = by_key(run(F.division_game(1), season_records=records))[("pressure_history", "postseason_record", "away")]["detail"]
        self.assertEqual((d["regular_season_games"], d["regular_season_win_pct"]), (162, round(100 / 162, 4)))

    def test_the_results_store_wins_where_both_hold_a_game(self):
        clash = dict(F.division_series()[0], away_score="99", home_score="0", winner="TB")
        r = run(F.division_game(2), F.world(), extra_games=[clash])
        self.assertEqual(r, run(F.division_game(2), F.world()))

    def test_a_club_spelled_two_ways_is_one_club(self):
        old = [F.g(8001, "2024-10-05", "OAK", "NYY", 1, 4, "D"), F.g(8002, "2024-10-06", "OAK", "NYY", 3, 2, "D")]
        new = [F.g(8101, "2025-09-20", "BOS", "ATH", 2, 1), F.g(8102, "2025-09-21", "BOS", "ATH", 2, 1)]
        r = run(F.game(1, "2025-09-28", "BOS", "ATH", "F", venue="Sutter Health Park"), new, extra_games=old)
        d = by_key(r)[("pressure_history", "postseason_record", "home")]
        self.assertEqual(d["value"], 2)         # the 2024 games under "OAK" count for "ATH"
        self.assertEqual(r["subject"]["home"], "ATH")      # and the page keeps the schedule's spelling


class TheSentences(unittest.TestCase):
    """Every number a sentence prints is a number the factor holds, so the analyst's critic,
    which strikes any number it cannot find in the packet, never strikes a quoted situation."""

    def records(self):
        out = [run(F.regular_game())]
        out += [run(F.division_game(n)) for n in (1, 3, 4, 5)]
        out.append(run(F.game(501, "2025-10-12", "TOR", "NYY", "L", venue="Yankee Stadium")))
        out.append(run(F.division_game(1), extra_games=TheLongerHistory().history()))
        out.append(run(F.game(601, "2025-10-20", "NYY", "TB", "L")))
        return out

    def test_every_number_in_every_sentence_is_held_by_its_factor(self):
        checked = 0
        for r in self.records():
            for f in r["factors"]:
                self.assertEqual(rec.unsupported_sentence_numbers(f), [],
                                 f"{f['family']}.{f['name']}.{f['side']}: {f['sentence']}")
                checked += 1
        self.assertGreater(checked, 150)

    def test_every_record_is_sound(self):
        for r in self.records():
            self.assertEqual(rec.problems(r), [])

    def test_no_sentence_uses_a_word_the_product_bans(self):
        banned = ("edge", "lock", "guarantee", "sure thing", "free money", "win probability",
                  "emotional intelligence", "+ev", "true line")
        for r in self.records():
            for f in r["factors"]:
                low = f["sentence"].lower()
                for word in banned:
                    self.assertNotIn(word, low, f["sentence"])
            for g in r["missing"]:
                self.assertNotIn("edge", g["reason"].lower())

    def test_a_sentence_is_one_sentence_that_ends_with_a_full_stop(self):
        for r in self.records():
            for f in r["factors"]:
                self.assertTrue(f["sentence"].endswith("."), f["sentence"])
                self.assertEqual(f["sentence"], f["sentence"].strip())


class TheDeterminism(unittest.TestCase):
    def test_the_same_inputs_give_the_same_record(self):
        self.assertEqual(run(F.division_game(4)), run(F.division_game(4)))

    def test_it_is_json_clean(self):
        import json
        json.dumps(run(F.division_game(4)), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
