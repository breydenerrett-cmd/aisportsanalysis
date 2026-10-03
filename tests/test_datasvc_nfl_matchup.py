"""src/datasvc/nfl/matchup.py: the fact sheet for one game, on the synthetic league of tests/_nfl_world.py.

Facts only: the market block is the market's own numbers, every difference is home minus away with
its two samples, every missing fact is listed as missing with its reason, and the sheet never prints the
game's own score. The store is injected; nothing reads data/datasvc/nfl.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from src.datasvc.nfl import features as F
from src.datasvc.nfl import matchup as M
from src.datasvc.nfl import venues
from tests import _nfl_world as W
from tests.test_datasvc_nfl_features import G, KICK, WorldCase

NOW = datetime(2025, 10, 20, 12, 0, tzinfo=timezone.utc)


class TheMarket(unittest.TestCase):
    def game(self, **over):
        base = {"spread_line": 3.5, "total_line": 47.5, "home_moneyline": -180, "away_moneyline": 155,
                "home_spread_odds": -110, "away_spread_odds": -110, "over_odds": -105, "under_odds": -115,
                "source": "nflverse:games.csv", "fetched_utc": "2025-10-20T12:00:00Z"}
        base.update(over)
        return base

    def test_the_market_by_hand(self):
        m = M.market_block(self.game())
        self.assertEqual((m["available"], m["as_of_safe"]), (True, False))
        self.assertEqual((m["source"], m["fetched_utc"]), ("nflverse:games.csv", "2025-10-20T12:00:00Z"))
        ml = m["moneyline"]                                # 180/280 = .6429 and 100/255 = .3922; together 1.0351
        self.assertEqual((ml["home"], ml["away"]), (-180, 155))
        self.assertEqual(ml["implied"], {"home": 0.6429, "away": 0.3922})
        self.assertEqual(ml["margin"], 0.0351)
        self.assertEqual(ml["without_margin"], {"home": 0.6211, "away": 0.3789})
        spread = m["spread"]
        self.assertEqual((spread["nflverse_spread_line"], spread["home"], spread["away"], spread["favourite"]), (3.5, -3.5, 3.5, "home"))
        self.assertEqual(spread["prices"]["implied"], {"home": 0.5238, "away": 0.5238})        # 110/210
        self.assertEqual((spread["prices"]["margin"], spread["prices"]["without_margin"]), (0.0476, {"home": 0.5, "away": 0.5}))
        total = m["total"]
        self.assertEqual(total["line"], 47.5)
        self.assertEqual(total["prices"]["implied"], {"over": 0.5122, "under": 0.5349})        # 105/205 and 115/215
        self.assertEqual(total["prices"]["margin"], 0.0471)
        self.assertEqual(total["prices"]["without_margin"], {"over": 0.4892, "under": 0.5108})

    def test_the_spread_is_read_both_ways_so_neither_is_a_guess(self):
        away = M.market_block(self.game(spread_line=-2.5))["spread"]
        self.assertEqual((away["nflverse_spread_line"], away["home"], away["away"], away["favourite"]), (-2.5, 2.5, -2.5, "away"))
        pick = M.market_block(self.game(spread_line=0.0))["spread"]
        self.assertEqual((pick["home"], pick["away"], pick["favourite"]), (0.0, 0.0, "pick"))
        none = M.market_block(self.game(spread_line=None))["spread"]
        self.assertEqual((none["home"], none["away"], none["favourite"]), (None, None, None))

    def test_a_price_that_cannot_be_american_is_absent(self):
        for bad in (0, 50, -99, "x", True, None, float("nan") if False else 99.5):
            self.assertIsNone(M.implied(bad), repr(bad))
        self.assertEqual(M.implied(100), 0.5)
        self.assertEqual(M.implied(-100), 0.5)
        self.assertEqual(M.implied(-200), 0.6667)
        self.assertEqual(M.implied(250), 0.2857)

    def test_one_missing_price_leaves_the_other_but_no_margin(self):
        m = M.market_block(self.game(away_moneyline=None))["moneyline"]
        self.assertEqual((m["home"], m["away"]), (-180, None))
        self.assertEqual(m["implied"], {"home": 0.6429, "away": None})
        self.assertEqual((m["margin"], m["without_margin"]), (None, {"home": None, "away": None}))
        junk = M.market_block(self.game(home_moneyline=0))["moneyline"]
        self.assertEqual((junk["home"], junk["margin"]), (None, None))

    def test_no_market_at_all_is_said_so(self):
        m = M.market_block(self.game(spread_line=None, total_line=None, home_moneyline=None, away_moneyline=None))
        self.assertEqual((m["available"], m["as_of_safe"]), (False, False))
        self.assertIn("no spread, total or moneyline", m["reason"])


class TheSheet(WorldCase):
    def sheet(self, name, **kw):
        return M.matchup(self.store, G[name], now=NOW, **kw)

    def test_the_shape(self):
        s = self.sheet("g14")
        self.assertEqual(set(s), {"game", "as_of", "as_of_source", "leakage_rule", "note", "schedule", "conditions", "home",
                                  "away", "head_to_head", "market", "differentials", "missing"})
        self.assertEqual((s["as_of"], s["as_of_source"]), (KICK["g14"], "kickoff"))
        self.assertEqual(s["note"], M.FACTS_ONLY)
        self.assertEqual(s["leakage_rule"], F.LEAKAGE_RULE)
        g = s["game"]
        self.assertEqual((g["home_team"], g["away_team"], g["home_name"], g["away_name"], g["status"], g["week"], g["season"]),
                         ("KC", "BUF", "Kansas City Chiefs", "Buffalo Bills", "scheduled", 8, 2025))

    def test_the_sheet_never_prints_the_games_own_score(self):
        for name in ("g14", "g05", "g12"):
            s = self.sheet(name)
            self.assertNotIn("home_score", s["game"])
            self.assertNotIn("away_score", s["game"])
            text = json.dumps({k: v for k, v in s.items() if k != "head_to_head"})
            self.assertNotIn('"home_score"', text)                    # the earlier meetings (head_to_head) show theirs
            self.assertNotIn('"away_score"', text)

    def test_a_game_already_played_still_gets_its_pre_game_sheet(self):
        s = self.sheet("g05")
        self.assertEqual(s["game"]["status"], "final")
        self.assertEqual(s["as_of"], KICK["g05"])
        self.assertEqual(s["home"]["sample"]["games"], 2)             # SEA before Sept 14: g02 and g04, never g05 itself
        self.assertEqual(s["away"]["sample"]["games"], 2)             # KC: g01 and g03

    def test_both_teams_blocks_are_the_features_the_other_module_computes(self):
        s = self.sheet("g14")
        f = F.game_features(self.store, G["g14"])
        self.assertEqual(s["home"], f["home"])
        self.assertEqual(s["away"], f["away"])
        self.assertEqual(s["head_to_head"], f["head_to_head"])
        self.assertEqual(s["schedule"], f["schedule"])

    def test_the_market_block_of_a_played_game_is_labelled_not_as_of(self):
        m = self.sheet("g03")["market"]
        self.assertEqual((m["available"], m["as_of_safe"], m["spread"]["home"], m["moneyline"]["home"]), (True, False, -3.0, -150))
        self.assertIn("Never an as-of-date price", m["note"])

    def test_a_game_with_no_market_lists_it_as_missing(self):
        s = self.sheet("g15")
        self.assertFalse(s["market"]["available"])
        self.assertIn(("market", None), {(m["figure"], m["side"]) for m in s["missing"]})

    def test_the_differentials_by_hand(self):
        d = self.sheet("g14")["differentials"]                         # KC (home) minus BUF (away)
        self.assertEqual(len(d), 23)
        # last 3: KC 27 for and 13.3333 against, margin 13.6667. BUF (g09 L 17-20, g11 W 30-27, g13 W 19-16): 22, 21, +1
        pf = d["form.last_3.points_for_per_game"]
        self.assertEqual((pf["home"], pf["away"], pf["diff"], pf["unit"], pf["home_sample"], pf["away_sample"], pf["thin_sample"]),
                         (27, 22, 5, "points per game", 3, 3, False))
        self.assertEqual(d["form.last_3.points_against_per_game"]["diff"], -7.6667)
        self.assertEqual(d["form.last_3.margin_per_game"]["diff"], 12.6667)
        self.assertEqual(d["form.last_5.points_for_per_game"]["home"], 25.6)
        self.assertEqual(d["form.last_5.points_for_per_game"]["away"], 25)                   # BUF: 31 + 28 + 17 + 30 + 19 = 125, over 5
        ypp = d["form.last_3.yards_per_play"]
        self.assertEqual((ypp["home"], ypp["home_sample"]), (6.0309, 3))
        rest = d["rest.days_since_last_game"]
        self.assertEqual((rest["home"], rest["away"], rest["diff"], rest["unit"], rest["thin_sample"]), (14, 7, 7, "days", False))
        miles = venues.miles_between("BUF00", "KAN00")
        self.assertEqual((d["travel.miles_from_home_base"]["home"], d["travel.miles_from_home_base"]["away"],
                          d["travel.miles_from_home_base"]["diff"]), (0.0, miles, round(0.0 - miles, 4)))
        self.assertEqual(d["travel.time_zones_crossed"], {"unit": "hours", "home": 0, "away": -1, "diff": 1,
                                                          "home_sample": None, "away_sample": None, "thin_sample": False})

    def test_a_difference_is_null_when_either_side_has_no_value_and_is_listed_missing(self):
        s = self.sheet("g14")
        inj = s["differentials"]["injuries.out"]
        self.assertEqual((inj["home"], inj["away"], inj["diff"], inj["thin_sample"]), (None, None, None, True))
        figures = {m["figure"] for m in s["missing"]}
        self.assertIn("differentials.injuries.out", figures)
        self.assertIn("injuries", figures)                              # each side's own entry too

    def test_a_window_with_fewer_games_than_it_names_is_a_thin_sample(self):
        d = self.sheet("g05")["differentials"]                          # SEA and KC each have only two games behind them
        self.assertTrue(d["form.last_3.points_for_per_game"]["thin_sample"])
        self.assertEqual((d["form.last_3.points_for_per_game"]["home_sample"], d["form.last_3.points_for_per_game"]["away_sample"]), (2, 2))
        self.assertTrue(d["form.season_to_date.points_for_per_game"]["thin_sample"])      # one 2025 game each... KC 1, SEA 1
        self.assertFalse(d["rest.days_since_last_game"]["thin_sample"])

    def test_injury_differentials_when_both_reports_are_in(self):
        d = self.sheet("g10")["differentials"]                          # KC (away) 4 listed, 1 out; ARI (home) 1 listed, 1 out
        self.assertEqual((d["injuries.out"]["home"], d["injuries.out"]["away"], d["injuries.out"]["diff"]), (1, 1, 0))
        self.assertEqual((d["injuries.listed"]["home"], d["injuries.listed"]["away"], d["injuries.listed"]["diff"]), (1, 4, -3))

    def test_the_missing_list_names_the_side_the_team_the_figure_and_the_reason(self):
        s = self.sheet("g13")
        rows = [m for m in s["missing"] if m["figure"] == "travel.venue"]
        self.assertEqual({(m["side"], m["team"]) for m in rows}, {("home", "BUF"), ("away", "SEA")})
        self.assertTrue(all("unreliable" in m["reason"] for m in rows))
        self.assertIn("differentials.travel.miles_from_home_base", {m["figure"] for m in s["missing"]})

    def test_an_explicit_as_of_before_the_kickoff_is_honoured_and_after_it_is_refused(self):
        s = self.sheet("g14", as_of="2025-10-01")
        self.assertEqual((s["as_of"], s["as_of_source"]), ("2025-10-01T00:00:00Z", "argument"))
        self.assertEqual(s["home"]["sample"]["games"], 4)
        with self.assertRaises(ValueError):
            self.sheet("g14", as_of="2025-10-27")
        with self.assertRaises(F.UnknownGame):
            M.matchup(self.store, "2099_01_AAA_BBB")

    def test_the_sheet_is_json(self):
        json.dumps(self.sheet("g14"))
        json.dumps(self.sheet("g01"))

    def test_the_first_game_in_the_store_is_a_sheet_of_blanks_each_with_a_reason(self):
        s = self.sheet("g01")
        self.assertEqual((s["home"]["sample"]["games"], s["away"]["sample"]["games"]), (0, 0))
        reasons = {m["figure"]: m["reason"] for m in s["missing"] if m["side"] == "home"}
        self.assertIn("form.last_3", reasons)
        self.assertIn("rest.days_since_last_game", reasons)
        self.assertIsNone(s["differentials"]["form.last_3.points_for_per_game"]["diff"])


class FindingTheGame(WorldCase):
    def test_two_teams_find_the_next_game_between_them(self):
        self.assertEqual(M.find_game(self.store, "KC", "BUF", now=NOW)["game_id"], G["g14"])
        self.assertEqual(M.find_game(self.store, "BUF", "KC", now=NOW)["game_id"], G["g14"])           # either order
        self.assertEqual(M.find_game(self.store, "chiefs", "bills", now=NOW)["game_id"], G["g14"])       # nicknames

    def test_with_no_game_still_to_come_it_is_the_latest_between_them(self):
        self.assertEqual(M.find_game(self.store, "KC", "SEA", now=NOW)["game_id"], G["g07"])             # g05 and g07 are behind
        later = NOW + timedelta(days=30)
        self.assertEqual(M.find_game(self.store, "KC", "BUF", now=later)["game_id"], G["g14"])

    def test_a_season_and_week_pick_the_game(self):
        self.assertEqual(M.find_game(self.store, "KC", "BUF", season=2025, week=1, now=NOW)["game_id"], G["g03"])
        self.assertEqual(M.find_game(self.store, "KC", "BUF", season=2024, now=NOW)["game_id"], G["g01"])

    def test_teams_that_do_not_meet_that_week_or_a_team_that_does_not_exist_or_the_same_team_twice(self):
        with self.assertRaises(LookupError) as caught:
            M.find_game(self.store, "KC", "BUF", season=2024, week=1, now=NOW)
        self.assertIn("no game between KC and BUF", str(caught.exception))
        with self.assertRaises(F.UnknownTeam):
            M.find_game(self.store, "KC", "ZZZ", now=NOW)
        with self.assertRaises(ValueError):
            M.find_game(self.store, "KC", "Chiefs", now=NOW)

    def test_a_removed_game_is_never_the_answer(self):
        store = self.variant(lambda rows: [r.update(status="removed") for r in rows["games"] if r["game_id"] == G["g14"]])
        self.assertEqual(M.find_game(store, "KC", "BUF", now=NOW)["game_id"], G["g03"])


if __name__ == "__main__":
    unittest.main()
