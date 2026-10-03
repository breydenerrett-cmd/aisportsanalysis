"""src/datasvc/nfl/features.py: leakage-free team, game and player features, on hand-checked cases.

Every expected number below was worked out by hand from the league in tests/_nfl_world.py (its
docstring lists the games). The store is injected: nothing here reads data/datasvc/nfl.

Two kinds of test:
  * the gate and each figure, on cases whose answer is written in the test;
  * the leakage property, run over every team and every game of the league: features as of a moment
    computed from the full store must equal those computed from a store that never had anything at or
    after that moment, and a deliberately leaky gate must fail that same check.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.datasvc.nfl import features as F
from src.datasvc.nfl import venues
from src.datasvc.nfl.store import NflStore
from tests import _nfl_world as W

G = {n: gid for n, gid in (
    ("g01", "2024_12_KC_BUF"), ("g02", "2024_18_ARI_SEA"), ("g03", "2025_01_BUF_KC"), ("g04", "2025_01_ARI_SEA"),
    ("g05", "2025_02_KC_SEA"), ("g06", "2025_02_ARI_BUF"), ("g07", "2025_03_SEA_KC"), ("g08", "2025_03_BUF_ARI"),
    ("g09", "2025_04_SEA_BUF"), ("g10", "2025_05_KC_ARI"), ("g11", "2025_05_BUF_SEA"), ("g12", "2025_06_ARI_KC"),
    ("g13", "2025_07_SEA_BUF"), ("g14", "2025_08_BUF_KC"), ("g15", "2025_08_SEA_ARI"))}
KICK = {name: W.eastern(g["gameday"], g["kickoff_et"]) for name in G for g in W._games() if g["game_id"] == G[name]}


def at(text: str) -> datetime:
    return F.parse_instant(text)


class WorldCase(unittest.TestCase):
    """A store over the synthetic league, built once for the class; `variant` makes an edited copy."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = W.build_world(Path(cls._tmp.name) / "world")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def variant(self, mutate) -> NflStore:
        rows = copy.deepcopy(W.world_rows())
        mutate(rows)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = NflStore(Path(tmp.name) / "variant")
        for name, data in rows.items():
            store.write(name, data)
        return store

    def game_ids(self, plays):
        return [p.game_id for p in plays]


class TheGate(WorldCase):
    def admitted(self, team, as_of, store=None, skipped=None):
        return self.game_ids(F.completed_games(store or self.store, team, as_of, skipped))

    def test_a_game_at_the_as_of_instant_or_later_never_counts(self):
        self.assertEqual(self.admitted("KC", KICK["g05"]), [G["g01"], G["g03"]])          # g05 is at the instant: out
        self.assertEqual(self.admitted("KC", KICK["g03"]), [G["g01"]])
        self.assertEqual(self.admitted("KC", KICK["g01"]), [])                            # the store's first game for KC

    def test_the_games_before_a_later_moment_are_all_there_and_in_order(self):
        self.assertEqual(self.admitted("KC", "2025-12-31"), [G["g01"], G["g03"], G["g05"], G["g07"], G["g10"], G["g12"]])
        self.assertEqual(self.admitted("SEA", "2025-12-31"), [G["g02"], G["g04"], G["g05"], G["g07"], G["g09"], G["g11"], G["g13"]])

    def test_a_game_scheduled_but_not_played_never_counts_whatever_the_moment(self):
        self.assertNotIn(G["g14"], self.admitted("KC", "2030-01-01"))
        self.assertNotIn(G["g15"], self.admitted("SEA", "2030-01-01"))

    def test_the_six_hour_finish_allowance(self):
        """The source has no finish time, so a game counts only six hours after its kickoff."""
        kickoff = at(KICK["g05"])
        skipped = F._new_skipped()
        before = self.admitted("KC", kickoff + timedelta(hours=5, minutes=59, seconds=59), skipped=skipped)
        self.assertEqual(before, [G["g01"], G["g03"]])
        self.assertEqual(skipped["in_progress_at_as_of"], [G["g05"]])                     # seen, named, not used
        self.assertEqual(self.admitted("KC", kickoff + timedelta(hours=6)), [G["g01"], G["g03"], G["g05"]])

    def test_a_bare_date_is_the_start_of_that_day_in_utc(self):
        self.assertEqual(self.admitted("KC", "2025-09-14"), [G["g01"], G["g03"]])         # the game on the as_of date: out
        self.assertEqual(self.admitted("KC", "2025-09-15"), [G["g01"], G["g03"], G["g05"]])

    def test_a_game_after_midnight_utc_belongs_to_the_next_utc_day(self):
        """The Thursday night game of 2025-09-04 (gameday Sept 4, Eastern) kicks off 00:20 UTC on Sept 5."""
        self.assertEqual(KICK["g03"], "2025-09-05T00:20:00Z")
        self.assertEqual(self.admitted("KC", "2025-09-05"), [G["g01"]])                   # conservative: not yet
        self.assertEqual(self.admitted("KC", "2025-09-06"), [G["g01"], G["g03"]])

    def test_a_game_that_should_have_finished_with_no_result_is_listed_never_counted(self):
        def mutate(rows):
            for table in ("games", "team_games"):
                for row in rows[table]:
                    if row["game_id"] == G["g07"]:
                        row["status"] = "no_result"
                        for field in ("home_score", "away_score", "points_for", "points_against", "margin", "result"):
                            if field in row:
                                row[field] = None
        store = self.variant(mutate)
        skipped = F._new_skipped()
        self.assertEqual(self.admitted("KC", W.NOW, store, skipped), [G["g01"], G["g03"], G["g05"], G["g10"], G["g12"]])
        self.assertEqual(skipped["started_without_result"],
                         [{"game_id": G["g07"], "kickoff_utc": KICK["g07"], "status": "no_result"}])

    def test_a_scheduled_game_whose_kickoff_has_long_passed_is_listed_too(self):
        """As of a moment after week 8, the store still has g14 as scheduled: it should have been played."""
        skipped = F._new_skipped()
        self.admitted("KC", "2025-12-31", skipped=skipped)
        self.assertEqual(skipped["started_without_result"],
                         [{"game_id": G["g14"], "kickoff_utc": KICK["g14"], "status": "scheduled"}])
        future = F._new_skipped()
        self.admitted("KC", W.NOW, skipped=future)                                         # before its kickoff: not an omission
        self.assertEqual(future["started_without_result"], [])

    def test_a_game_the_source_still_calls_in_progress_never_counts_even_with_scores(self):
        store = self.variant(lambda rows: [row.update(status="in_progress") for row in rows["games"] if row["game_id"] == G["g12"]])
        skipped = F._new_skipped()
        self.assertNotIn(G["g12"], self.admitted("KC", W.NOW, store, skipped))
        self.assertEqual([s["game_id"] for s in skipped["started_without_result"]], [G["g12"]])

    def test_a_game_with_no_kickoff_time_is_excluded_not_assumed_to_be_in_the_past(self):
        store = self.variant(lambda rows: [row.update(kickoff_utc=None) for row in rows["games"] if row["game_id"] == G["g05"]])
        skipped = F._new_skipped()
        self.assertNotIn(G["g05"], self.admitted("KC", "2025-12-31", store, skipped))
        self.assertEqual(skipped["no_kickoff_time"], [G["g05"]])

    def test_an_unreadable_as_of_raises(self):
        with self.assertRaises(ValueError):
            F.completed_games(self.store, "KC", "yesterday")
        with self.assertRaises(ValueError):
            F.team_features_as_of(self.store, "KC", "2025-13-45")

    def test_the_sides_of_a_game_are_read_from_the_teams_own_view(self):
        plays = F.completed_games(self.store, "KC", "2025-12-31")
        by = {p.game_id: p for p in plays}
        self.assertEqual((by[G["g01"]].site, by[G["g01"]].points_for, by[G["g01"]].points_against, by[G["g01"]].result),
                         ("away", 21, 30, "L"))
        self.assertEqual((by[G["g03"]].site, by[G["g03"]].points_for, by[G["g03"]].result), ("home", 27, "W"))
        self.assertEqual((by[G["g12"]].site, by[G["g12"]].opponent), ("neutral", "ARI"))
        self.assertEqual(by[G["g12"]].margin, 7)


class TeamForm(WorldCase):
    def features(self, team, as_of, **kw):
        return F.team_features_as_of(self.store, team, as_of, **kw)

    def test_kansas_city_as_of_its_week_eight_kickoff_by_hand(self):
        f = self.features("KC", KICK["g14"])
        self.assertEqual(f["sample"]["games"], 6)
        self.assertEqual(f["record"], {"season": {"games": 5, "wins": 4, "losses": 1, "ties": 0},
                                       "store": {"games": 6, "wins": 4, "losses": 2, "ties": 0}})
        self.assertEqual(f["streak"], {"type": "W", "length": 3})
        three = f["form"]["last_3"]                     # g07 W 31-17, g10 W 30-10, g12 W 20-13
        self.assertEqual((three["games"], three["wins"], three["losses"], three["points_for"], three["points_against"]),
                         (3, 3, 0, 81, 40))
        self.assertEqual((three["points_for_per_game"], three["points_against_per_game"], three["margin_per_game"]),
                         (27, 13.3333, 13.6667))
        self.assertEqual(three["yards_per_play"]["value"], 6.0309)                        # 1170 net yards over 194 plays
        self.assertEqual((three["yards_per_play"]["num"], three["yards_per_play"]["den"], three["yards_per_play"]["games"]),
                         (1170, 194, 3))
        self.assertEqual(three["yards_per_play_allowed"]["value"], 4.2941)               # 730 over 170
        self.assertEqual((three["turnover_margin"]["value"], three["turnover_margin"]["total"]), (1.6667, 5))
        self.assertEqual((three["first_game_utc"], three["last_game_utc"]), (KICK["g07"], KICK["g12"]))
        five = f["form"]["last_5"]                      # adds g03 W 27-24 and g05 L 20-24
        self.assertEqual((five["games"], five["wins"], five["losses"], five["points_for"], five["points_against"]),
                         (5, 4, 1, 128, 88))
        self.assertEqual((five["points_for_per_game"], five["points_against_per_game"], five["margin_per_game"]),
                         (25.6, 17.6, 8))
        self.assertEqual(five["yards_per_play"]["value"], 5.7911)                         # 1830 over 316
        self.assertEqual(five["yards_per_play_allowed"]["value"], 4.7782)                 # 1400 over 293
        self.assertEqual((five["turnover_margin"]["value"], five["turnover_margin"]["total"]), (1, 5))
        season = f["form"]["season_to_date"]            # the five 2025 games
        self.assertEqual((season["games"], season["points_for"], season["points_against"]), (5, 128, 88))
        self.assertEqual(season["games_in_target_season"], 5)

    def test_seattle_with_a_losing_run_by_hand(self):
        f = self.features("SEA", KICK["g15"])
        three = f["form"]["last_3"]                     # g09 W 20-17, g11 L 27-30, g13 L 16-19
        self.assertEqual((three["wins"], three["losses"], three["points_for"], three["points_against"]), (1, 2, 63, 66))
        self.assertEqual((three["points_for_per_game"], three["points_against_per_game"], three["margin_per_game"]),
                         (21, 22, -1))
        self.assertEqual(three["yards_per_play"]["value"], 5.1323)                        # 970 over 189
        self.assertEqual(three["yards_per_play_allowed"]["value"], 5.1053)                # 970 over 190
        self.assertEqual((three["turnover_margin"]["value"], three["turnover_margin"]["total"]), (0.6667, 2))
        self.assertEqual(f["streak"], {"type": "L", "length": 2})
        season = f["form"]["season_to_date"]
        self.assertEqual((season["games"], season["wins"], season["losses"], season["points_for"], season["points_against"]),
                         (6, 3, 3, 125, 134))
        self.assertEqual((season["points_for_per_game"], season["points_against_per_game"]), (20.8333, 22.3333))
        self.assertEqual(f["record"]["store"], {"games": 7, "wins": 4, "losses": 3, "ties": 0})     # g02 counts: last season

    def test_the_last_games_are_listed_newest_first_with_their_lines(self):
        f = self.features("KC", KICK["g14"])
        self.assertEqual([g["game_id"] for g in f["last_games"]], [G["g12"], G["g10"], G["g07"], G["g05"], G["g03"]])
        newest = f["last_games"][0]
        self.assertEqual((newest["opponent"], newest["site"], newest["points_for"], newest["points_against"], newest["result"],
                          newest["margin"], newest["week"], newest["season"]), ("ARI", "neutral", 20, 13, "W", 7, 6, 2025))

    def test_a_window_that_reaches_into_last_season_says_so(self):
        f = self.features("KC", KICK["g05"])            # KC's games before: g01 (2024) and g03
        five = f["form"]["last_5"]
        self.assertEqual((five["games"], five["seasons"], five["games_in_target_season"]), (2, [2024, 2025], 1))
        self.assertEqual(f["form"]["season_to_date"]["games"], 1)
        self.assertEqual(f["season"], 2025)

    def test_a_team_with_no_game_in_the_season_yet_has_a_thin_window_and_lists_what_is_missing(self):
        f = self.features("KC", KICK["g03"])            # the 2025 opener: only g01 from last season
        self.assertEqual(f["form"]["season_to_date"]["games"], 0)
        self.assertIsNone(f["form"]["season_to_date"]["points_for_per_game"])
        self.assertEqual({m["figure"] for m in f["missing"]}, {"form.season_to_date"})
        first = self.features("KC", KICK["g01"])        # nothing at all before the store's first game
        self.assertEqual(first["sample"]["games"], 0)
        self.assertEqual(first["streak"], {"type": None, "length": 0})
        self.assertEqual({m["figure"] for m in first["missing"]}, {"form.last_3", "form.last_5", "form.season_to_date", "rest"})
        self.assertIsNone(first["rest"]["days_since_last_game"])

    def test_a_figure_with_no_statistics_behind_it_is_missing_not_zero(self):
        def mutate(rows):
            for row in rows["team_games"]:
                if row["game_id"] in (G["g10"], G["g12"]):
                    row.update(has_stats=False, net_yards=None, plays=None, yards_per_play=None, giveaways=None,
                               takeaways=None, turnover_margin=None)
        store = self.variant(mutate)
        f = F.team_features_as_of(store, "KC", KICK["g14"])
        three = f["form"]["last_3"]                     # only g07 has statistics now
        self.assertEqual((three["points_for"], three["games"]), (81, 3))                   # results are the schedule's
        self.assertEqual((three["yards_per_play"]["value"], three["yards_per_play"]["games"]), (6.1538, 1))   # 400 over 65
        self.assertEqual((three["turnover_margin"]["value"], three["turnover_margin"]["games"]), (1, 1))
        none_left = F.team_features_as_of(self.variant(lambda r: [t.update(net_yards=None) for t in r["team_games"]]), "KC", KICK["g14"])
        figure = none_left["form"]["last_3"]["yards_per_play"]
        self.assertEqual((figure["value"], figure["games"]), (None, 0))
        self.assertIn("none of the 3 game(s) has plays and net yards", figure["reason"])
        self.assertIn("form.last_3.yards_per_play", {m["figure"] for m in none_left["missing"]})

    def test_the_rest_figure_of_a_team_measures_to_the_as_of_date(self):
        f = self.features("KC", "2025-10-20T12:00:00Z")   # NOW; the last game was g12 on Oct 12
        self.assertEqual((f["rest"]["days_since_last_game"], f["rest"]["last_game_id"]), (8, G["g12"]))

    def test_a_team_is_found_by_nickname_or_alias_and_an_unknown_one_raises(self):
        self.assertEqual(F.team_features_as_of(self.store, "chiefs", KICK["g14"])["team"], "KC")
        self.assertEqual(F.resolve_team(self.store, "Seattle Seahawks"), "SEA")
        with self.assertRaises(F.UnknownTeam):
            F.team_features_as_of(self.store, "XYZ", KICK["g14"])
        with self.assertRaises(F.UnknownTeam):
            F.resolve_team(self.store, "DAL")                # a real team the store has no game for


class RestByTheSchedule(WorldCase):
    def rest(self, name, side):
        return F.game_features(self.store, G[name])[side]["rest"]

    def test_a_season_opener_has_no_rest_figure_and_says_why(self):
        r = self.rest("g03", "home")                      # KC's last game was last November
        self.assertEqual((r["season_opener"], r["days_since_last_game"], r["short_week"], r["coming_off_bye"]),
                         (True, None, None, None))
        self.assertIn("season opener", r["reason"])
        self.assertEqual(r["last_game_id"], G["g01"])

    def test_the_first_game_in_the_store_has_nothing_before_it(self):
        r = self.rest("g01", "away")
        self.assertEqual((r["season_opener"], r["days_since_last_game"], r["last_game_id"]), (None, None, None))
        self.assertIn("no earlier game", r["reason"])

    def test_sunday_to_sunday_is_seven_days_and_not_a_short_week(self):
        r = self.rest("g09", "home")                      # BUF: Sunday Sept 21 to Sunday Sept 28
        self.assertEqual((r["days_since_last_game"], r["week_gap"], r["short_week"], r["coming_off_bye"], r["last_game_id"]),
                         (7, 1, False, False, G["g08"]))

    def test_thursday_after_sunday_is_a_short_week(self):
        for side in ("home", "away"):                     # g07 Thu Sept 18: KC and SEA both played Sunday Sept 14
            r = self.rest("g07", side)
            self.assertEqual((r["days_since_last_game"], r["short_week"], r["coming_off_bye"], r["week_gap"]), (4, True, False, 1), side)

    def test_ten_days_after_a_thursday_game_is_neither_short_nor_a_bye(self):
        r = self.rest("g05", "away")                      # KC played Thu Sept 4 (g03), then Sun Sept 14 at Seattle
        self.assertEqual((r["days_since_last_game"], r["short_week"], r["coming_off_bye"]), (10, False, False))
        r = self.rest("g09", "away")                      # SEA: Thu Sept 18 to Sun Sept 28
        self.assertEqual((r["days_since_last_game"], r["short_week"], r["coming_off_bye"], r["week_gap"]), (10, False, False, 1))

    def test_a_missed_week_is_a_bye(self):
        r = self.rest("g10", "away")                      # KC: Thu Sept 18, week 4 off, Sun Oct 5
        self.assertEqual((r["days_since_last_game"], r["week_gap"], r["coming_off_bye"], r["short_week"]), (17, 2, True, False))
        r = self.rest("g10", "home")                      # ARI: Sun Sept 21, week 4 off, Sun Oct 5
        self.assertEqual((r["days_since_last_game"], r["week_gap"], r["coming_off_bye"]), (14, 2, True))
        r = self.rest("g14", "home")                      # KC again: week 7 off
        self.assertEqual((r["days_since_last_game"], r["week_gap"], r["coming_off_bye"]), (14, 2, True))

    def test_two_weeks_of_rest_with_no_missed_week_number_is_still_a_bye(self):
        """The Super Bowl: conference championship in week 21, the final in week 22, two weeks apart."""
        prev = {"game_id": "2025_21_X_Y", "season": 2025, "week": 21, "gameday": "2026-01-25", "kickoff_utc": "2026-01-25T23:30:00Z"}
        game = {"game_id": "2025_22_X_Z", "season": 2025, "week": 22, "gameday": "2026-02-08"}
        r = F.rest_facts(prev, game, "home")
        self.assertEqual((r["days_since_last_game"], r["week_gap"], r["coming_off_bye"], r["short_week"]), (14, 1, True, False))

    def test_the_source_rest_figure_is_passed_through_beside_ours(self):
        r = self.rest("g07", "home")
        self.assertEqual(r["source_rest_days"], 4)

    def test_rest_is_measured_from_the_previous_scheduled_game_even_when_it_has_no_result_yet(self):
        """Rest, bye and travel are schedule facts: they do not wait for the previous game to be played."""
        f = F.game_features(self.store, G["g15"], as_of="2025-10-21")                       # ARI hosts SEA in week 8
        self.assertEqual(f["home"]["rest"]["last_game_id"], G["g12"])                      # its London game; week 7 was the bye
        self.assertEqual((f["home"]["rest"]["days_since_last_game"], f["home"]["rest"]["coming_off_bye"]), (14, True))
        # a game weeks ahead: the previous scheduled game has not been played, and the rest is still right
        def mutate(rows):
            for row in rows["games"]:
                if row["game_id"] == G["g13"]:
                    row.update(status="scheduled", home_score=None, away_score=None, overtime=None)
        store = self.variant(mutate)
        r = F.game_features(store, G["g14"], as_of="2025-10-12T00:00:00Z")["away"]["rest"]    # BUF: previous scheduled game is g13
        self.assertEqual((r["last_game_id"], r["days_since_last_game"]), (G["g13"], 7))

    def test_an_unfinished_run_up_to_a_game_is_named_so_the_form_is_not_mistaken_for_current(self):
        f = F.game_features(self.store, G["g14"], as_of="2025-10-12T00:00:00Z")
        gap = f["home"]["sample"]["scheduled_games_without_a_finished_result_before_this_game"]
        self.assertEqual(gap, [G["g12"]])                  # g12 kicks off Oct 12 13:30Z: after this as_of
        self.assertIn("form", {m["figure"] for m in f["home"]["missing"]})


class Travel(WorldCase):
    def travel(self, name, side):
        return F.game_features(self.store, G[name])[side]["travel"]

    def test_a_home_team_travels_nowhere(self):
        t = self.travel("g08", "home")                     # ARI at PHO00
        self.assertEqual((t["miles_from_home_base"], t["time_zones_crossed"], t["direction"], t["base_stadium_id"]),
                         (0.0, 0, "none", "PHO00"))

    def test_kansas_city_to_seattle_crosses_two_zones_west(self):
        t = self.travel("g05", "away")
        self.assertEqual(t["miles_from_home_base"], venues.miles_between("KAN00", "SEA00"))
        self.assertAlmostEqual(t["miles_from_home_base"], 1508.8, delta=1)
        self.assertEqual((t["time_zones_crossed"], t["direction"], t["venue_stadium_id"]), (-2, "west", "SEA00"))
        self.assertEqual(t["kickoff_home_base_clock"], "12:00")                           # 1 pm Eastern is noon in Kansas City
        self.assertEqual(t["miles_from_last_game"], venues.miles_between("KAN00", "SEA00"))   # the previous game was at home

    def test_arizona_does_not_change_its_clocks_so_it_is_three_hours_behind_buffalo_in_september(self):
        t = self.travel("g06", "away")                     # ARI at BUF, Sept 14: Arizona MST -7, Buffalo EDT -4
        self.assertEqual((t["time_zones_crossed"], t["direction"]), (3, "east"))
        self.assertEqual(t["kickoff_home_base_clock"], "10:00")                           # 17:00 UTC is 10 am in Arizona
        self.assertEqual(t["miles_from_home_base"], venues.miles_between("PHO00", "BUF00"))
        t = self.travel("g08", "away")                     # BUF at ARI, Sept 21
        self.assertEqual((t["time_zones_crossed"], t["direction"], t["kickoff_home_base_clock"]), (-3, "west", "16:05"))

    def test_arizona_is_on_pacific_time_in_summer_and_an_hour_ahead_of_it_in_winter(self):
        base = next(g for g in W._games() if g["game_id"] == G["g05"])                     # KC at SEA
        summer = dict(base, away_team="ARI", kickoff_utc="2025-09-14T17:00:00Z")
        winter = dict(base, away_team="ARI", kickoff_utc="2025-12-14T18:00:00Z")
        self.assertEqual(F.travel_facts(self.store, "ARI", summer, None)["time_zones_crossed"], 0)       # -7 and -7
        self.assertEqual(F.travel_facts(self.store, "ARI", winter, None)["time_zones_crossed"], -1)      # -7 and -8

    def test_a_neutral_game_in_london_is_travel_for_both_teams(self):
        kc, ari = self.travel("g12", "home"), self.travel("g12", "away")
        self.assertEqual(kc["miles_from_home_base"], venues.miles_between("KAN00", "LON02"))
        self.assertGreater(kc["miles_from_home_base"], 4000)                               # the "home" team flies too
        self.assertEqual((kc["time_zones_crossed"], kc["kickoff_home_base_clock"]), (6, "08:30"))          # BST +1 against CDT -5
        self.assertEqual((ari["time_zones_crossed"], ari["kickoff_home_base_clock"]), (8, "06:30"))        # BST +1 against MST -7
        self.assertEqual(ari["miles_from_home_base"], venues.miles_between("PHO00", "LON02"))
        # KC came to London from Phoenix, where it had played the week before
        self.assertEqual(kc["miles_from_last_game"], venues.miles_between("PHO00", "LON02"))

    def test_a_venue_the_schedule_names_wrongly_gives_no_distance_and_says_why(self):
        for side in ("home", "away"):
            t = self.travel("g13", side)
            self.assertEqual((t["miles_from_home_base"], t["time_zones_crossed"], t["kickoff_home_base_clock"]), (None, None, None))
            self.assertIn("unreliable", t["reasons"]["venue"])
            self.assertIn("nominal_home_stadium_on_neutral_site", t["reasons"]["venue"])
        f = F.game_features(self.store, G["g13"])
        self.assertIn("travel.venue", {m["figure"] for m in f["home"]["missing"]})

    def test_the_trip_after_a_game_at_an_unusable_venue_has_no_last_game_distance(self):
        t = self.travel("g14", "away")                     # BUF's previous scheduled game is g13
        self.assertEqual(t["miles_from_home_base"], venues.miles_between("BUF00", "KAN00"))
        self.assertIsNone(t["miles_from_last_game"])
        self.assertIn("previous game's venue is unusable", t["reasons"]["last_game"])

    def test_the_trip_home_from_london_is_measured_from_london(self):
        t = self.travel("g14", "home")                     # KC at home after London
        self.assertEqual((t["miles_from_home_base"], t["time_zones_crossed"]), (0.0, 0))
        self.assertEqual(t["miles_from_last_game"], venues.miles_between("LON02", "KAN00"))

    def test_a_stadium_not_in_the_table_is_unknown_not_guessed(self):
        store = self.variant(lambda rows: [r.update(stadium_id="XXX99") for r in rows["games"] if r["game_id"] == G["g05"]])
        t = F.game_features(store, G["g05"])["away"]["travel"]
        self.assertIsNone(t["miles_from_home_base"])
        self.assertIn("not in the venue table", t["reasons"]["venue"])

    def test_a_game_with_no_kickoff_time_has_distance_but_no_time_zone_figure(self):
        store = self.variant(lambda rows: [r.update(kickoff_utc=None) for r in rows["games"] if r["game_id"] == G["g14"]])
        t = F.game_features(store, G["g14"], as_of="2025-10-24")["away"]["travel"]
        self.assertIsNotNone(t["miles_from_home_base"])
        self.assertIsNone(t["time_zones_crossed"])
        self.assertEqual(t["reasons"]["time_zones"], "no kickoff time")

    def test_the_home_stadium_comes_from_the_schedule_of_that_season(self):
        self.assertEqual(F._home_base(self.store, "KC", 2025), "KAN00")
        self.assertIsNone(F._home_base(self.store, "KC", 2024))                            # no home game that season, none earlier
        self.assertEqual(F._home_base(self.store, "KC", 2027), "KAN00")                    # falls back to the nearest earlier season
        self.assertIsNone(F._home_base(self.store, "DAL", 2025))


class TheSchedulesOwnFacts(WorldCase):
    def facts(self, name):
        return F.schedule_facts(next(g for g in W._games() if g["game_id"] == G[name]))

    def test_a_thursday_night_game_is_primetime(self):
        f = self.facts("g03")
        self.assertEqual((f["primetime"], f["time_window"], f["weekday"], f["kickoff_et"], f["divisional"]),
                         (True, "night", "Thursday", "20:20", False))

    def test_the_sunday_slots(self):
        self.assertEqual((self.facts("g05")["primetime"], self.facts("g05")["time_window"]), (False, "early"))            # 13:00
        self.assertEqual((self.facts("g04")["primetime"], self.facts("g04")["time_window"]), (False, "late_afternoon"))  # 16:25
        self.assertEqual((self.facts("g12")["primetime"], self.facts("g12")["time_window"]), (False, "early"))          # 09:30

    def test_divisional_comes_from_the_schedule(self):
        self.assertTrue(self.facts("g04")["divisional"])
        self.assertFalse(self.facts("g05")["divisional"])
        self.assertTrue(self.facts("g02")["divisional"])

    def test_postseason_and_neutral_flags(self):
        self.assertEqual((self.facts("g12")["neutral_site"], self.facts("g12")["postseason"]), (True, False))
        playoff = F.schedule_facts(dict(next(g for g in W._games() if g["game_id"] == G["g05"]), game_type="DIV", week=20))
        self.assertTrue(playoff["postseason"])

    def test_a_game_with_no_kickoff_clock_has_no_slot(self):
        f = F.schedule_facts(dict(next(g for g in W._games() if g["game_id"] == G["g05"]), kickoff_et=None))
        self.assertEqual((f["primetime"], f["time_window"]), (None, None))


class TheStartingQuarterbackAndCoach(WorldCase):
    def qb(self, name, side):
        return F.game_features(self.store, G[name])[side]["qb"]

    def test_a_change_of_quarterback_since_the_last_game(self):
        q = self.qb("g09", "away")                         # SEA's backup starts at BUF
        self.assertEqual((q["last_game"]["qb_id"], q["this_game"]["qb_id"], q["this_game"]["changed_since_last_game"]),
                         ("00-SEAQB1", "00-SEAQB2", True))
        self.assertEqual((q["this_game"]["prior_starts_in_store"], q["this_game"]["prior_starts_with_team"]), (0, 0))   # his first start
        self.assertEqual(q["last_game"]["game_id"], G["g07"])

    def test_the_same_backup_again_is_not_a_change_and_has_one_prior_start(self):
        q = self.qb("g11", "home")
        self.assertEqual((q["this_game"]["qb_id"], q["this_game"]["changed_since_last_game"],
                          q["this_game"]["prior_starts_in_store"], q["this_game"]["prior_starts_with_team"]), ("00-SEAQB2", False, 1, 1))

    def test_the_starter_returning_is_a_change_and_his_starts_are_counted_before_the_game_only(self):
        q = self.qb("g13", "away")
        self.assertEqual((q["this_game"]["qb_id"], q["this_game"]["changed_since_last_game"]), ("00-SEAQB1", True))
        self.assertEqual(q["this_game"]["prior_starts_in_store"], 4)                       # g02, g04, g05, g07; not g09 or g11 (QB2) nor g13

    def test_a_quarterback_with_no_change_and_a_long_run_of_starts(self):
        q = self.qb("g14", "home")
        self.assertEqual((q["this_game"]["qb_id"], q["this_game"]["changed_since_last_game"],
                          q["this_game"]["prior_starts_in_store"]), ("00-KCQB1", False, 6))      # g01 (last season), g03, g05, g07, g10, g12

    def test_a_game_not_yet_played_has_a_projected_starter_and_the_block_says_it_is_not_as_of_safe(self):
        q = self.qb("g14", "home")
        self.assertTrue(q["this_game"]["projected"])
        self.assertIs(q["this_game"]["as_of_safe"], False)
        self.assertIs(q["last_game"]["as_of_safe"], True)
        self.assertFalse(self.qb("g12", "home")["this_game"]["projected"])

    def test_no_listed_starter_is_null_and_listed_missing(self):
        store = self.variant(lambda rows: [r.update(home_qb_id=None, home_qb_name=None) for r in rows["games"] if r["game_id"] == G["g14"]])
        f = F.game_features(store, G["g14"])
        q = f["home"]["qb"]["this_game"]
        self.assertEqual((q["qb_id"], q["changed_since_last_game"], q["prior_starts_in_store"]), (None, None, None))
        self.assertIn("qb.this_game", {m["figure"] for m in f["home"]["missing"]})

    def test_the_head_coach_and_a_change_of_coach(self):
        c = F.game_features(self.store, G["g13"])["away"]["coach"]                         # SEA's interim coach from week 7
        self.assertEqual((c["last_game"]["coach"], c["this_game"]["coach"], c["this_game"]["changed_since_last_game"]),
                         ("Coach Hawks", "Interim Hawks", True))
        c = F.game_features(self.store, G["g14"])["home"]["coach"]
        self.assertEqual((c["this_game"]["coach"], c["this_game"]["changed_since_last_game"]), ("Coach Chiefs", False))
        self.assertIs(c["this_game"]["as_of_safe"], False)


class InjuryReports(WorldCase):
    def injuries(self, name, side, as_of=None):
        return F.game_features(self.store, G[name], as_of)[side]["injuries"]

    def test_counts_by_position_as_of_the_kickoff_by_hand(self):
        i = self.injuries("g10", "away")                   # KC at ARI; four rows, all stamped before the kickoff
        self.assertTrue(i["available"])
        self.assertEqual((i["players_listed"], i["rows_not_yet_known"], i["report_week"]), (4, 0, 5))
        self.assertEqual(i["totals"], {"listed": 4, "out": 1, "doubtful": 1, "questionable": 1, "dnp": 2, "limited": 2})
        self.assertEqual(i["by_position_group"], {
            "QB": {"listed": 1, "out": 0, "doubtful": 0, "questionable": 1, "dnp": 0, "limited": 1},
            "WR": {"listed": 1, "out": 1, "doubtful": 0, "questionable": 0, "dnp": 1, "limited": 0},
            "OL": {"listed": 1, "out": 0, "doubtful": 1, "questionable": 0, "dnp": 1, "limited": 0},
            "DB": {"listed": 1, "out": 0, "doubtful": 0, "questionable": 0, "dnp": 0, "limited": 1}})
        self.assertEqual(i["newest_report_utc"], "2025-10-03T20:00:00Z")
        self.assertEqual([(p["position"], p["report_status"]) for p in i["skill_players_listed"]],
                         [("QB", "questionable"), ("WR", "out")])

    def test_a_row_stamped_after_the_kickoff_is_never_used(self):
        i = self.injuries("g10", "home")                   # ARI: the running back's row is stamped Oct 6, after the game
        self.assertEqual((i["players_listed"], i["rows_not_yet_known"]), (1, 1))
        self.assertEqual(i["totals"]["out"], 1)
        self.assertNotIn("RB", i["by_position_group"])
        self.assertEqual([p["position"] for p in i["skill_players_listed"]], [])

    def test_an_as_of_before_a_report_was_out_does_not_see_it(self):
        i = F.game_features(self.store, G["g10"], as_of="2025-10-03T20:30:00Z")
        self.assertEqual(i["away"]["injuries"]["players_listed"], 4)                       # KC's rows are stamped 20:00 and earlier
        self.assertFalse(i["home"]["injuries"]["available"])                               # ARI's are stamped 21:00 and Oct 6
        self.assertEqual(i["home"]["injuries"]["rows_not_yet_known"], 2)
        self.assertIn("injuries", {m["figure"] for m in i["home"]["missing"]})
        earlier = F.game_features(self.store, G["g10"], as_of="2025-10-02T20:00:00Z")["away"]["injuries"]
        self.assertEqual(earlier["players_listed"], 1)                                     # only the defensive back's, stamped Oct 2 20:00

    def test_a_row_with_no_timestamp_is_taken_as_out_24_hours_before_kickoff(self):
        kickoff = at(KICK["g12"])
        i = F.game_features(self.store, G["g12"], as_of=kickoff - timedelta(hours=24))["home"]["injuries"]
        self.assertTrue(i["available"])
        self.assertEqual((i["players_listed"], i["timestamped_rows"], i["newest_report_utc"]), (1, 0, None))
        self.assertIn("24 hours before kickoff", i["assumption"])
        early = F.game_features(self.store, G["g12"], as_of=kickoff - timedelta(hours=24, seconds=1))["home"]["injuries"]
        self.assertFalse(early["available"])
        self.assertEqual(early["rows_not_yet_known"], 1)

    def test_a_week_with_no_injury_rows_at_all_is_unavailable_not_zero(self):
        for name in ("g13", "g14", "g03"):
            i = self.injuries(name, "home")
            self.assertEqual(i["available"], False, name)
            self.assertIn("no injury report rows for week", i["reason"])

    def test_a_team_with_no_one_on_a_published_week_has_an_empty_report(self):
        # week 6 is published (KC's row stays); ARI has nobody listed, which is zero, not missing
        store = self.variant(lambda rows: rows.update(injuries=[r for r in rows["injuries"] if r["team"] != "ARI"]))
        empty = F.game_features(store, G["g12"])["away"]["injuries"]
        self.assertEqual((empty["available"], empty["players_listed"], empty["totals"]["listed"]), (True, 0, 0))
        self.assertEqual(empty["by_position_group"], {})

    def test_every_injury_row_of_a_team_counts_once(self):
        i = self.injuries("g10", "away")
        self.assertEqual(sum(g["listed"] for g in i["by_position_group"].values()), i["totals"]["listed"])


class HeadToHead(WorldCase):
    def h2h(self, name, as_of=None):
        return F.game_features(self.store, G[name], as_of)["head_to_head"]

    def test_kansas_city_and_buffalo_before_week_eight_by_hand(self):
        h = self.h2h("g14")                                # home KC, away BUF
        self.assertEqual((h["meetings"], h["home_team"], h["away_team"]), (2, "KC", "BUF"))
        self.assertEqual((h["home_team_wins"], h["away_team_wins"], h["ties"]), (1, 1, 0))
        self.assertEqual(h["average_margin_for_home_team"], -3)                            # KC lost by 9 at BUF, won by 3 at home
        self.assertEqual([m["game_id"] for m in h["items"]], [G["g03"], G["g01"]])         # newest first
        self.assertEqual(h["last_meeting"]["game_id"], G["g03"])
        self.assertEqual((h["last_meeting"]["winner"], h["last_meeting"]["margin_for_target_home_team"]), ("KC", 3))
        self.assertEqual(h["items"][1]["winner"], "BUF")
        self.assertEqual(h["items"][1]["margin_for_target_home_team"], -9)

    def test_only_meetings_before_the_game_count(self):
        h = self.h2h("g03")                                # BUF at KC in week 1: only last season's meeting is behind it
        self.assertEqual((h["meetings"], h["home_team_wins"], h["away_team_wins"]), (1, 0, 1))
        self.assertEqual(h["last_meeting"]["game_id"], G["g01"])

    def test_no_meeting_in_the_window_is_zero_and_said_so(self):
        h = self.h2h("g01")
        self.assertEqual((h["meetings"], h["last_meeting"], h["average_margin_for_home_team"], h["items"]), (0, None, None, []))
        self.assertEqual(h["store_window"]["seasons"], [2024, 2025])
        self.assertIn("store's window", h["note"])

    def test_a_meeting_on_the_as_of_day_is_not_behind_it(self):
        h = F.head_to_head(self.store, "KC", "ARI", at("2025-10-12T00:00:00Z"))
        self.assertEqual(h["meetings"], 1)                 # g10 (Oct 5) is before Oct 12; g12 is on the as_of day
        self.assertEqual(h["last_meeting"]["game_id"], G["g10"])
        self.assertEqual(F.head_to_head(self.store, "KC", "ARI", at("2025-10-13T00:00:00Z"))["meetings"], 2)

    def test_a_rematch_the_same_week_never_counts_itself(self):
        h = F.head_to_head(self.store, "BUF", "SEA", at(KICK["g13"]))
        self.assertEqual([m["game_id"] for m in h["items"]], [G["g11"], G["g09"]])


class AGamesFeatures(WorldCase):
    def test_the_default_as_of_is_the_kickoff(self):
        f = F.game_features(self.store, G["g05"])
        self.assertEqual((f["as_of"], f["as_of_source"]), (KICK["g05"], "kickoff"))
        self.assertEqual(f["home"]["team"], "SEA")
        self.assertEqual(f["away"]["team"], "KC")
        self.assertEqual(f["home"]["sample"]["games"], 2)  # SEA's g02 (last season) and g04
        self.assertEqual(f["leakage_rule"], F.LEAKAGE_RULE)

    def test_an_earlier_explicit_as_of_is_honoured(self):
        f = F.game_features(self.store, G["g14"], as_of="2025-10-01")
        self.assertEqual((f["as_of"], f["as_of_source"]), ("2025-10-01T00:00:00Z", "argument"))
        self.assertEqual(f["home"]["sample"]["games"], 4)                                  # KC's g01, g03, g05, g07

    def test_an_as_of_after_the_kickoff_is_refused_because_it_would_count_the_games_own_result(self):
        with self.assertRaises(ValueError) as caught:
            F.game_features(self.store, G["g05"], as_of=at(KICK["g05"]) + timedelta(seconds=1))
        self.assertIn("after the kickoff", str(caught.exception))
        F.game_features(self.store, G["g05"], as_of=KICK["g05"])                            # at the kickoff is fine

    def test_an_unknown_game_and_a_game_with_no_kickoff_time(self):
        with self.assertRaises(F.UnknownGame):
            F.game_features(self.store, "2099_01_AAA_BBB")
        store = self.variant(lambda rows: [r.update(kickoff_utc=None) for r in rows["games"] if r["game_id"] == G["g14"]])
        with self.assertRaises(ValueError):
            F.game_features(store, G["g14"])
        self.assertEqual(F.game_features(store, G["g14"], as_of="2025-10-24")["as_of_source"], "argument")

    def test_conditions_and_the_listed_quarterback_are_labelled_not_as_of_safe(self):
        f = F.game_features(self.store, G["g05"])
        self.assertEqual((f["conditions"]["temp_f"], f["conditions"]["wind_mph"], f["conditions"]["as_of_safe"]), (70, 5, False))
        self.assertIs(f["home"]["qb"]["this_game"]["as_of_safe"], False)
        self.assertIs(f["home"]["coach"]["this_game"]["as_of_safe"], False)
        self.assertNotIn("as_of_safe", f["schedule"])                                       # the schedule's facts need no label

    def test_the_game_block_has_no_score(self):
        f = F.game_features(self.store, G["g05"])
        self.assertNotIn("home_score", f["game"])
        self.assertNotIn("away_score", f["game"])

    def test_the_missing_list_names_the_side_and_the_team(self):
        f = F.game_features(self.store, G["g13"])           # an unusable venue and no injury rows for week 7
        pairs = {(m["side"], m["team"], m["figure"]) for m in f["missing"]}
        self.assertIn(("home", "BUF", "travel.venue"), pairs)
        self.assertIn(("away", "SEA", "injuries"), pairs)


def corrupt_future(store: NflStore, before: str, root: Path, keep_injuries_of: str = None) -> NflStore:
    """The same store with every game that had not finished by `before` filled with nonsense results.

    A game had not finished by `before` if its kickoff plus the six-hour allowance is after it: that is the
    games to come, the game at the instant, and the games under way. Their scores, statistics, player lines,
    market and conditions become absurd numbers (a 777-3 overtime win, 9,999 yards, 999 targets) and their
    injury rows are flipped, while the SCHEDULE (who plays whom, when, where, the listed starters) is left as it
    was, because the schedule is public in advance. Features as of `before` must not move: the nonsense can only
    reach them through a gate that lets an unfinished game in. (`keep_injuries_of` is the one game whose injury
    reports are known beforehand and are therefore left alone.)
    """
    rows = {name: copy.deepcopy(store.load(name)) for name in ("games", "team_games", "player_games", "injuries")}
    cut = F.parse_instant(before)
    unfinished = {g["game_id"] for g in rows["games"]
                  if not g.get("kickoff_utc") or F.parse_instant(g["kickoff_utc"]) + F.FINISH_ALLOWANCE > cut}
    home = {g["game_id"]: g["home_team"] for g in rows["games"]}
    for g in rows["games"]:
        if g["game_id"] in unfinished:
            g.update(status="final", home_score=777, away_score=3, overtime=True, temp_f=-40, wind_mph=99,
                     spread_line=99.5, total_line=1.5, home_moneyline=-9999, away_moneyline=9999)
    for r in rows["team_games"]:
        if r["game_id"] in unfinished:
            at_home = r["team"] == home[r["game_id"]]
            r.update(status="final", points_for=777 if at_home else 3, points_against=3 if at_home else 777,
                     margin=774 if at_home else -774, result="W" if at_home else "L", overtime=True, has_stats=True,
                     net_yards=9999, plays=1, yards_per_play=9999.0, giveaways=99, takeaways=0, turnover_margin=-99)
    for r in rows["player_games"]:
        if r["game_id"] in unfinished:
            r.update(pass_attempts=999, completions=999, passing_yards=999, passing_tds=99, interceptions=99, carries=999,
                     rushing_yards=999, rushing_tds=99, targets=999, receptions=999, receiving_yards=999,
                     receiving_tds=99, target_share=0.99, air_yards_share=0.99)
    for r in rows["injuries"]:
        if r["game_id"] in unfinished and r["game_id"] != keep_injuries_of:
            r.update(report_status="out", practice_status="dnp", date_modified="2000-01-01T00:00:00Z")
    out = NflStore(root)
    for name, data in rows.items():
        out.write(name, data)
    return out


def without_labelled_blocks(value):
    """The same structure with every block that says `as_of_safe: false` (and store metadata) removed."""
    if isinstance(value, dict):
        if value.get("as_of_safe") is False:
            return None
        return {k: without_labelled_blocks(v) for k, v in value.items() if k not in ("store_window", "game", "status")}
    if isinstance(value, list):
        return [without_labelled_blocks(v) for v in value]
    return value


class TheLeakageProperty(WorldCase):
    """Features as of a moment must not move when everything that had not finished by then is made nonsense."""

    def check_everything(self, tmp: Path) -> int:
        checked = 0
        for game in self.store.games:
            before = game["kickoff_utc"]
            noisy = corrupt_future(self.store, before, tmp / f"noisy_{checked}", keep_injuries_of=game["game_id"])
            for team in (game["home_team"], game["away_team"]):
                self.assertEqual(F.team_features_as_of(self.store, team, before),
                                 F.team_features_as_of(noisy, team, before), (game["game_id"], team))
            self.assertEqual(without_labelled_blocks(F.game_features(self.store, game["game_id"])),
                             without_labelled_blocks(F.game_features(noisy, game["game_id"])), game["game_id"])
            checked += 1
        return checked

    def test_team_and_game_features_ignore_every_game_that_has_not_finished_by_their_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check_everything(Path(tmp)), 15)

    def test_the_same_holds_at_arbitrary_moments_between_games_and_inside_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            moments = []
            for g in self.store.games:
                kickoff = at(g["kickoff_utc"])
                moments += [kickoff - timedelta(seconds=1), kickoff + timedelta(hours=1), kickoff + timedelta(hours=5, minutes=59),
                            kickoff + timedelta(hours=6), kickoff + timedelta(days=1)]
            for i, moment in enumerate(moments):
                stamp = F.iso_utc(moment)
                noisy = corrupt_future(self.store, stamp, Path(tmp) / f"m{i}")
                for team in ("KC", "BUF", "SEA", "ARI"):
                    self.assertEqual(F.team_features_as_of(self.store, team, stamp), F.team_features_as_of(noisy, team, stamp),
                                     (stamp, team))

    def test_player_features_ignore_every_game_that_has_not_finished_by_their_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, g in enumerate(self.store.games):
                for offset in (timedelta(0), timedelta(hours=3), timedelta(hours=6)):
                    stamp = F.iso_utc(at(g["kickoff_utc"]) + offset)
                    noisy = corrupt_future(self.store, stamp, Path(tmp) / f"p{i}_{int(offset.total_seconds())}")
                    for pid in ("00-KCWR1", "00-KCQB1", "00-KCTE1", "00-MOVER1"):
                        self.assertEqual(F.player_features_as_of(self.store, pid, stamp),
                                         F.player_features_as_of(noisy, pid, stamp), (stamp, pid))

    def test_the_nonsense_really_would_have_moved_the_figures_had_it_got_in(self):
        """Guard against a check that passes only because the corruption changes nothing: at a far later moment,
        when those games have long finished, the same figures do differ."""
        with tempfile.TemporaryDirectory() as tmp:
            noisy = corrupt_future(self.store, KICK["g05"], Path(tmp) / "n")
            late = "2030-01-01T00:00:00Z"
            self.assertNotEqual(F.team_features_as_of(self.store, "KC", late), F.team_features_as_of(noisy, "KC", late))
            self.assertNotEqual(F.player_features_as_of(self.store, "00-KCWR1", late),
                                F.player_features_as_of(noisy, "00-KCWR1", late))
            plays = F.completed_games(noisy, "KC", late)
            self.assertIn(777, [p.points_for for p in plays])

    def test_a_negative_allowance_lets_unfinished_games_in_and_the_player_and_team_checks_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp = KICK["g10"]
            noisy = corrupt_future(self.store, stamp, Path(tmp) / "n")                      # corrupted under the real rule
            with mock.patch.object(F, "FINISH_ALLOWANCE", timedelta(days=-60)):             # now every game counts as finished
                self.assertNotEqual(F.player_features_as_of(self.store, "00-KCWR1", stamp),
                                    F.player_features_as_of(noisy, "00-KCWR1", stamp))
                self.assertNotEqual(F.team_features_as_of(self.store, "KC", stamp), F.team_features_as_of(noisy, "KC", stamp))
            self.assertEqual(F.player_features_as_of(self.store, "00-KCWR1", stamp),
                             F.player_features_as_of(noisy, "00-KCWR1", stamp))             # and with the real rule they agree

    def test_a_deliberately_leaky_gate_is_caught_by_this_very_check(self):
        """If the gate admitted games at and after as_of, check_everything must fail: prove the test has teeth."""
        real = F.completed_games

        def leaky(store, team, before, skipped=None):
            return real(store, team, F.parse_instant(before) + timedelta(days=30), skipped)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(F, "completed_games", leaky):
            with self.assertRaises(AssertionError):
                self.check_everything(Path(tmp))

    def test_a_gate_that_forgets_the_finish_allowance_is_caught_too(self):
        """Admitting the game at the instant, or one still under way, moves the nonsense into the figures."""
        real = F.completed_games

        def at_the_instant(store, team, before, skipped=None):
            return real(store, team, F.parse_instant(before) + F.FINISH_ALLOWANCE, skipped)     # a game at `before` now counts

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(F, "completed_games", at_the_instant):
            with self.assertRaises(AssertionError):
                self.check_everything(Path(tmp))



class PlayerFeatures(WorldCase):
    def features(self, pid, as_of):
        return F.player_features_as_of(self.store, pid, as_of)

    def test_a_receiver_over_his_last_three_and_five_games_by_hand(self):
        f = self.features("00-KCWR1", KICK["g14"])        # rows: g03, g05, g10, g12 (none in g07)
        self.assertEqual((f["name"], f["position"], f["position_group"], f["team"]), ("Kay See", "WR", "WR", "KC"))
        self.assertEqual(f["sample"]["games_in_store_before_as_of"], 4)
        three = f["last_3"]                                # g05, g10, g12
        self.assertEqual(three["games"], 3)
        self.assertEqual(three["stats"]["targets"], {"total": 20, "per_game": 6.6667, "games": 3})
        self.assertEqual(three["stats"]["receptions"]["total"], 13)
        self.assertEqual(three["stats"]["receiving_yards"], {"total": 165, "per_game": 55, "games": 3})
        self.assertEqual(three["stats"]["receiving_tds"]["total"], 1)
        self.assertEqual(three["stats"]["carries"]["total"], 0)
        self.assertEqual(three["shares"]["target_share"], {"mean": 0.2133, "games": 3})   # (0.16 + 0.20 + 0.28) / 3
        self.assertEqual(three["game_ids"], [G["g12"], G["g10"], G["g05"]])
        five = f["last_5"]                                 # only four rows exist: the window says 4, not 5
        self.assertEqual(five["games"], 4)
        self.assertEqual(five["stats"]["targets"], {"total": 28, "per_game": 7, "games": 4})
        self.assertEqual(five["stats"]["receiving_yards"]["total"], 255)
        self.assertEqual([g["game_id"] for g in f["recent_games"]], [G["g12"], G["g10"], G["g05"], G["g03"]])

    def test_a_game_the_team_played_without_the_player_is_listed_as_missed(self):
        f = self.features("00-KCWR1", KICK["g14"])
        self.assertEqual(f["last_3"]["missed_team_games"], [G["g07"]])                      # KC played g07; he has no row
        self.assertEqual(f["last_3"]["team_games_in_span"], 4)                              # g05, g07, g10, g12
        self.assertEqual(f["last_5"]["missed_team_games"], [G["g07"]])
        self.assertEqual(f["last_5"]["team_games_in_span"], 5)

    def test_a_quarterbacks_passing_and_running_by_hand(self):
        f = self.features("00-KCQB1", KICK["g14"])         # g07, g10, g12
        s = f["last_3"]["stats"]
        self.assertEqual(s["pass_attempts"], {"total": 92, "per_game": 30.6667, "games": 3})
        self.assertEqual(s["completions"]["total"], 64)
        self.assertEqual(s["passing_yards"], {"total": 800, "per_game": 266.6667, "games": 3})
        self.assertEqual((s["passing_tds"]["total"], s["interceptions"]["total"]), (6, 1))
        self.assertEqual((s["carries"]["total"], s["rushing_yards"]["total"]), (7, 33))
        self.assertEqual(f["last_3"]["missed_team_games"], [])
        self.assertEqual(f["last_5"]["games"], 5)
        self.assertEqual(f["last_5"]["stats"]["pass_attempts"]["total"], 157)               # 30 + 35 + 28 + 33 + 31

    def test_a_row_of_zeros_is_a_game_played_not_a_gap(self):
        f = self.features("00-KCTE1", KICK["g14"])       # g03 all zeros, g05 four targets
        self.assertEqual(f["last_3"]["games"], 2)
        self.assertEqual(f["last_3"]["stats"]["targets"], {"total": 4, "per_game": 2, "games": 2})
        self.assertEqual(f["last_3"]["shares"]["target_share"], {"mean": None, "games": 0})

    def test_a_player_traded_mid_season_is_counted_only_against_his_current_teams_games(self):
        f = self.features("00-MOVER1", KICK["g14"])        # BUF in g03, g06; SEA in g09, g11
        self.assertEqual(f["team"], "SEA")
        self.assertEqual(f["last_3"]["game_ids"], [G["g11"], G["g09"], G["g06"]])
        self.assertEqual(f["last_3"]["stats"]["carries"], {"total": 45, "per_game": 15, "games": 3})
        self.assertEqual(f["last_3"]["missed_team_games"], [G["g13"]])                      # SEA's g13; not BUF's games of weeks 3 and 4
        self.assertEqual(f["last_3"]["team_games_in_span"], 3)                              # SEA's g09, g11, g13
        self.assertEqual(f["last_5"]["games"], 4)
        self.assertEqual(f["last_5"]["stats"]["carries"], {"total": 57, "per_game": 14.25, "games": 4})

    def test_only_rows_of_finished_games_before_the_moment_count(self):
        f = self.features("00-KCWR1", KICK["g10"])        # at g10's own kickoff: g03, g05 only
        self.assertEqual(f["sample"]["games_in_store_before_as_of"], 2)
        self.assertEqual(f["last_3"]["games"], 2)
        self.assertEqual(f["last_3"]["stats"]["targets"]["total"], 13)
        in_play = self.features("00-KCWR1", at(KICK["g10"]) + timedelta(hours=2))          # g10 itself is under way
        self.assertEqual(in_play["sample"]["games_in_store_before_as_of"], 2)
        self.assertEqual(in_play["sample"]["skipped"]["in_progress_at_as_of"], [G["g10"]])
        after = self.features("00-KCWR1", at(KICK["g10"]) + timedelta(hours=6))
        self.assertEqual(after["sample"]["games_in_store_before_as_of"], 3)

    def test_before_a_players_first_game_the_windows_are_empty_and_listed_missing(self):
        f = self.features("00-KCWR1", KICK["g01"])
        self.assertEqual(f["sample"]["games_in_store_before_as_of"], 0)
        self.assertEqual((f["last_3"]["games"], f["last_3"]["stats"]["targets"]["total"], f["last_3"]["stats"]["targets"]["per_game"]),
                         (0, None, None))
        self.assertEqual([m["figure"] for m in f["missing"]], ["last_3", "last_5"])
        self.assertIsNone(f["team"])

    def test_a_player_the_store_does_not_have_raises(self):
        with self.assertRaises(F.UnknownPlayer):
            self.features("00-NOBODY", KICK["g14"])

    def test_windows_can_be_asked_for(self):
        f = F.player_features_as_of(self.store, "00-KCQB1", KICK["g14"], windows=(1, 2))
        self.assertEqual((f["last_1"]["games"], f["last_2"]["games"]), (1, 2))
        self.assertEqual(f["last_1"]["stats"]["passing_yards"]["total"], 260)
        self.assertNotIn("last_3", f)
        self.assertEqual(len(f["recent_games"]), 2)

    def test_the_recent_games_carry_the_whole_stat_line(self):
        line = self.features("00-KCQB1", KICK["g14"])["recent_games"][0]
        self.assertEqual((line["game_id"], line["opponent"], line["pass_attempts"], line["passing_yards"], line["week"]),
                         (G["g12"], "ARI", 31, 260, 6))


if __name__ == "__main__":
    unittest.main()
