"""The matchup and team-strength conditions of the rule language (head_to_head, venue_record, scoring_rate,
league_rank, matchup_edge): what each one counts, on a fixture league built in this file and re-derived here
by brute force, so a test never checks the code against itself.

The story these pin (2026-10-19, a member's text "use statistics, previous head-to-head matchups ... home
advantage and away games data matched with offensive [and defensive stats]"): the builder had no condition for
any of it, so the parser read one stray word ("away") and the rest was thrown to a translator that could only
answer with conditions that were not on the menu either. Each of those ideas is now a row of the menu, bounded,
point in time (nothing dated on or after the slate day, nothing that was still being played at the lock) and
honest about thin data (a record or rank needs the games it names, otherwise the condition does not apply).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import render
from src.hounds.user_facts import FactBook, season_of

DATE = "2026-10-20"
LOCK = datetime(2026, 10, 20, 21, 10, tzinfo=timezone.utc)

# Ten clubs. Offensive rating o, defensive rating d (a bigger d lets in fewer runs).
CLUBS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]
O = {c: 10 + i for i, c in enumerate(CLUBS)}                       # AAA scores 10 ... JJJ scores 19
D = dict(zip(CLUBS, [5, 0, 9, 2, 7, 4, 1, 8, 3, 6]))             # a permutation of 0..9


def league_rows():
    """Every ordered pair (home, away) once, one game a day (so no club plays twice in a day and the order
    of a club's games is unambiguous). Home scores o[home] - d[away]; away scores o[away] - d[home]."""
    rows, i = [], 0
    for home in CLUBS:
        for away in CLUBS:
            if home == away:
                continue
            day = (datetime(2026, 6, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            rows.append({"date": day, "start_utc": f"{day}T23:10:00Z", "home": home, "away": away,
                         "home_score": O[home] - D[away], "away_score": O[away] - D[home], "game_pk": f"p{i}"})
            i += 1
    return rows


def ctx(home="AAA", away="BBB", pick="AAA", **over) -> R.Ctx:
    base = dict(sport="MLB", market="moneyline", side="home", line=None, price=120, n_books=5, home_code=home,
                away_code=away, home_name=home, away_name=away, pick_code=pick,
                opp_code=away if pick == home else home, date=DATE, lock=LOCK, game_pk="1", event_id="e1",
                seed="s", facts=None)
    base.update(over)
    return R.Ctx(**base)


def cond(cid, **params):
    item = R.default_instance(cid)
    item.update(params)
    return item


def holds(item, c):
    return R.BY_ID[item["id"]].fn(item, c)


def brute(rows, club, n):
    """Runs scored and allowed per game over the club's last n games before DATE, from the raw rows."""
    mine = []
    for g in sorted(rows, key=lambda g: (g["date"], g["game_pk"])):
        if g["date"] >= DATE:
            continue
        if g["home"] == club:
            mine.append((g["home_score"], g["away_score"]))
        elif g["away"] == club:
            mine.append((g["away_score"], g["home_score"]))
    mine = mine[-n:] if n else mine
    return sum(a for a, _ in mine) / len(mine), sum(b for _, b in mine) / len(mine)


class HeadToHead(unittest.TestCase):
    def facts(self):
        def g(day, home, away, hs, as_, hour="23:10:00Z"):
            return {"date": day, "start_utc": f"{day}T{hour}", "home": home, "away": away, "home_score": hs,
                    "away_score": as_, "game_pk": f"{day}{home}"}
        # BOS-SEA meetings: three from the earlier seasons (history only), two this autumn on file, then one ON
        # the slate date and one the day after that BOS won 9-0 (neither may ever be counted).
        history = [g("2025-04-01", "BOS", "SEA", 5, 1), g("2025-05-01", "SEA", "BOS", 4, 2),   # BOS won, SEA won
                   g("2025-06-01", "SEA", "BOS", 1, 3)]                                        # BOS won
        recent = [g("2026-09-01", "BOS", "SEA", 6, 2), g("2026-09-05", "SEA", "BOS", 5, 0),    # BOS won, SEA won
                  g("2026-10-20", "BOS", "SEA", 9, 0), g("2026-10-21", "BOS", "SEA", 9, 0)]
        return FactBook(mlb_games=recent, mlb_history=history + recent)

    def test_the_last_n_meetings_all_time_count_earlier_seasons(self):
        f = self.facts()
        # on file before the slate day: 2025-04, 05, 06, 2026-09-01, 09-05
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 5, "all", DATE, LOCK), (3, 5))
        self.assertEqual(f.head_to_head("MLB", "SEA", "BOS", 5, "all", DATE, LOCK), (2, 5))
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 2, "all", DATE, LOCK), (1, 2))
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 1, "all", DATE, LOCK), (0, 1))     # 09-05: SEA won

    def test_it_never_extrapolates_from_fewer_meetings_than_asked(self):
        f = self.facts()
        self.assertIsNone(f.head_to_head("MLB", "BOS", "SEA", 6, "all", DATE, LOCK))
        self.assertIsNone(f.head_to_head("MLB", "BOS", "TEX", 1, "all", DATE, LOCK))              # never met
        self.assertIsNone(f.head_to_head("MLB", "BOS", None, 1, "all", DATE, LOCK))

    def test_the_season_window_counts_only_this_seasons_meetings(self):
        f = self.facts()
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 2, "season", DATE, LOCK), (1, 2))
        self.assertIsNone(f.head_to_head("MLB", "BOS", "SEA", 3, "season", DATE, LOCK))        # only two this year

    def test_nothing_on_or_after_the_slate_day_and_nothing_still_being_played_at_the_lock_is_counted(self):
        f = self.facts()
        # the slate-day game (BOS won 9-0) and the day-after game would make it (1, 1) / (4, 5) if leaked
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 1, "season", DATE, LOCK), (0, 1))
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 5, "all", DATE, LOCK)[0], 3)

    def test_a_game_from_the_night_before_that_was_still_being_played_at_an_early_lock_is_not_counted(self):
        night = {"date": "2026-10-19", "start_utc": "2026-10-19T21:30:00Z", "home": "SEA", "away": "BOS",
                 "home_score": 0, "away_score": 9, "game_pk": "night"}
        f = FactBook(mlb_games=[night])
        early = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)      # 21:30Z + the 5 hour lag is after this
        self.assertIsNone(f.head_to_head("MLB", "BOS", "SEA", 1, "season", DATE, early))
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 1, "season", DATE, LOCK), (1, 1))

    def test_without_a_history_list_the_all_window_is_the_plain_list(self):
        recent = self.facts()._rows("mlb")
        f = FactBook(mlb_games=recent)
        self.assertEqual(f.head_to_head("MLB", "BOS", "SEA", 2, "all", DATE, LOCK), (1, 2))
        self.assertIsNone(f.head_to_head("MLB", "BOS", "SEA", 5, "all", DATE, LOCK))

    def test_nfl_seasons_run_september_to_february(self):
        self.assertEqual(season_of("NFL", "2026-01-04"), "2025")
        self.assertEqual(season_of("NFL", "2026-09-13"), "2026")
        self.assertEqual(season_of("MLB", "2026-01-04"), "2026")
        rows = [{"date": "2025-12-28", "start_utc": "2025-12-28T18:00:00Z", "home": "KC", "away": "DEN",
                 "home_score": 20, "away_score": 17},
                {"date": "2026-01-04", "start_utc": "2026-01-04T18:00:00Z", "home": "DEN", "away": "KC",
                 "home_score": 10, "away_score": 13},
                {"date": "2026-09-13", "start_utc": "2026-09-13T17:00:00Z", "home": "KC", "away": "DEN",
                 "home_score": 31, "away_score": 7}]
        f = FactBook(nfl_games=rows)
        # played on 2026-10-04 at 18:00Z; both of the earlier-calendar-year games are the SAME 2025 season
        self.assertEqual(f.head_to_head("NFL", "KC", "DEN", 2, "season", "2026-01-11", LOCK), (2, 2))
        self.assertIsNone(f.head_to_head("NFL", "KC", "DEN", 3, "season", "2026-10-04", LOCK))
        self.assertEqual(f.head_to_head("NFL", "KC", "DEN", 3, "all", "2026-10-04", LOCK), (3, 3))

    def test_the_condition_reads_each_team_against_the_other_for_pick_opponent_either_and_both(self):
        f = self.facts()
        c = ctx(home="BOS", away="SEA", pick="BOS", facts=f)
        base = dict(n=5, cmp="gte", wins=3, window="all")
        self.assertTrue(holds(cond("head_to_head", who="pick", **base), c))          # BOS won 3 of 5
        self.assertFalse(holds(cond("head_to_head", who="opponent", **base), c))     # SEA won 2 of 5
        self.assertTrue(holds(cond("head_to_head", who="either", **base), c))
        self.assertFalse(holds(cond("head_to_head", who="both", **base), c))
        self.assertTrue(holds(cond("head_to_head", who="both", n=5, cmp="gte", wins=2, window="all"), c))
        self.assertIsNone(holds(cond("head_to_head", who="pick", n=9, cmp="gte", wins=3, window="all"), c))

    def test_no_pick_team_means_not_known_not_false(self):
        c = ctx(home="BOS", away="SEA", pick=None, facts=self.facts())
        self.assertIsNone(holds(cond("head_to_head", who="pick"), c))


class VenueRecord(unittest.TestCase):
    def facts(self):
        rows = []
        # AAA at home this season: W W W W L (4 of 5); on the road: L L L W (1 of 4)
        for i, (won, home) in enumerate([(True, True)] * 4 + [(False, True)] + [(False, False)] * 3 + [(True, False)]):
            day = f"2026-09-{1 + i:02d}"
            me, them = (5, 2) if won else (2, 5)
            rows.append({"date": day, "start_utc": f"{day}T23:10:00Z", "home": "AAA" if home else "ZZZ",
                         "away": "ZZZ" if home else "AAA", "home_score": me if home else them,
                         "away_score": them if home else me, "game_pk": f"v{i}"})
        # a home game on the slate day that AAA lost badly must not count
        rows.append({"date": DATE, "start_utc": f"{DATE}T17:00:00Z", "home": "AAA", "away": "ZZZ", "home_score": 0,
                     "away_score": 9, "game_pk": "today"})
        return FactBook(mlb_games=rows)

    def test_the_season_split_is_wins_and_games_on_that_ground(self):
        f = self.facts()
        self.assertEqual(f.season_split("MLB", "AAA", True, DATE, LOCK), (4, 5))
        self.assertEqual(f.season_split("MLB", "AAA", False, DATE, LOCK), (1, 4))

    def test_today_means_home_for_the_home_team_and_road_for_the_visitor(self):
        f = self.facts()
        home_ctx = ctx(home="AAA", away="ZZZ", pick="AAA", facts=f)
        road_ctx = ctx(home="ZZZ", away="AAA", pick="AAA", facts=f)
        want = cond("venue_record", ground="today", cmp="gte", pct=75.0)
        self.assertTrue(holds(want, home_ctx))        # 80% at home
        self.assertIsNone(holds(want, road_ctx))      # 4 road games: under the 5-game minimum, so no verdict
        self.assertTrue(holds(cond("venue_record", ground="home", cmp="gte", pct=75.0), road_ctx))
        self.assertFalse(holds(cond("venue_record", ground="home", cmp="lt", pct=75.0), road_ctx))

    def test_fewer_than_five_games_on_the_ground_is_not_a_record(self):
        c = ctx(home="ZZZ", away="AAA", pick="AAA", facts=self.facts())
        self.assertIsNone(holds(cond("venue_record", ground="road", cmp="lte", pct=50.0), c))

    def test_a_team_that_is_neither_home_nor_away_has_no_ground_today(self):
        c = ctx(home="ZZZ", away="YYY", pick="AAA", facts=self.facts())
        self.assertIsNone(holds(cond("venue_record", ground="today"), c))


class TeamStrength(unittest.TestCase):
    def setUp(self):
        self.rows = league_rows()
        self.facts = FactBook(mlb_games=self.rows)

    def test_scoring_per_game_is_the_mean_of_the_last_n_games_before_the_slate_day(self):
        for club in ("AAA", "FFF", "JJJ"):
            for n in (3, 10, 0):
                got = self.facts.scoring("MLB", club, n, DATE, LOCK)
                pf, pa = brute(self.rows, club, n)
                self.assertAlmostEqual(got["pf"], pf, places=9, msg=(club, n))
                self.assertAlmostEqual(got["pa"], pa, places=9, msg=(club, n))

    def test_a_window_needs_every_game_it_names(self):
        self.assertIsNone(self.facts.scoring("MLB", "AAA", 19, DATE, LOCK))      # each club has played 18
        thin = FactBook(mlb_games=self.rows[:3])
        self.assertIsNone(thin.scoring("MLB", "AAA", 0, DATE, LOCK))           # under 5 games this season
        self.assertIsNone(thin.scoring("MLB", "AAA", 5, DATE, LOCK))
        self.assertIsNone(thin.scoring("MLB", "ZZZ", 3, DATE, LOCK))

    def test_ranks_are_one_for_the_best_and_clubs_level_on_the_figure_share_a_rank(self):
        # offense: JJJ scores the most; pf is o[c] - mean(d of the others), so the order follows o
        order = sorted(CLUBS, key=lambda c: -O[c])
        for want, club in enumerate(order, start=1):
            self.assertEqual(self.facts.scoring_rank("MLB", club, "offense", 0, DATE, LOCK), (want, 10), club)
        # defense: pa = mean(o of the others) - d[club]; the club with the biggest d allows the least
        best_d = sorted(CLUBS, key=lambda c: -D[c])
        allowed = {c: brute(self.rows, c, 0)[1] for c in CLUBS}          # runs allowed per game, from the raw rows
        for club in CLUBS:
            want = 1 + sum(1 for other in CLUBS if allowed[other] < allowed[club] - 1e-9)
            self.assertEqual(self.facts.scoring_rank("MLB", club, "defense", 0, DATE, LOCK), (want, 10), club)
        self.assertEqual(best_d[0], "CCC")                                  # the biggest d allows the fewest
        self.assertEqual(self.facts.scoring_rank("MLB", "CCC", "defense", 0, DATE, LOCK)[0], 1)
        tied = [dict(g, home_score=5, away_score=5) for g in self.rows]   # every club scores 5 a game
        f = FactBook(mlb_games=tied)
        self.assertEqual({f.scoring_rank("MLB", c, "offense", 0, DATE, LOCK)[0] for c in CLUBS}, {1})

    def test_too_few_clubs_is_not_a_league(self):
        f = FactBook(mlb_games=[g for g in self.rows if g["home"] in CLUBS[:4] and g["away"] in CLUBS[:4]])
        self.assertIsNone(f.scoring_rank("MLB", "AAA", "offense", 0, DATE, LOCK))

    def test_scoring_rate_compares_a_clubs_own_figure(self):
        c = ctx(home="JJJ", away="AAA", pick="JJJ", facts=self.facts)
        pf, pa = brute(self.rows, "JJJ", 10)
        self.assertTrue(holds(cond("scoring_rate", who="pick", unit="offense", n=10, cmp="gte", value=round(pf - 0.2, 1)), c))
        self.assertFalse(holds(cond("scoring_rate", who="pick", unit="offense", n=10, cmp="gte", value=round(pf + 0.2, 1)), c))
        self.assertTrue(holds(cond("scoring_rate", who="pick", unit="defense", n=10, cmp="lte", value=round(pa + 0.2, 1)), c))
        # the opponent is AAA
        pf_a, _ = brute(self.rows, "AAA", 10)
        self.assertTrue(holds(cond("scoring_rate", who="opponent", unit="offense", n=10, cmp="lte", value=round(pf_a + 0.2, 1)), c))
        self.assertIsNone(holds(cond("scoring_rate", who="pick", unit="offense", n=20), c))     # 18 games on file

    def test_league_rank_top_and_bottom(self):
        top = ctx(home="JJJ", away="AAA", pick="JJJ", facts=self.facts)       # JJJ: best offense, AAA: worst
        self.assertTrue(holds(cond("league_rank", who="pick", unit="offense", end="top", places=1, n=0), top))
        self.assertFalse(holds(cond("league_rank", who="opponent", unit="offense", end="top", places=5, n=0), top))
        self.assertTrue(holds(cond("league_rank", who="opponent", unit="offense", end="bottom", places=1, n=0), top))
        self.assertFalse(holds(cond("league_rank", who="pick", unit="offense", end="bottom", places=9, n=0), top))
        self.assertTrue(holds(cond("league_rank", who="both", unit="offense", end="top", places=10, n=0), top))

    def test_matchup_edge_compares_one_clubs_offense_rank_with_the_others_defense_rank(self):
        rows, f = self.rows, self.facts
        # JJJ has the #1 offense; its opponent HHH has a strong defense (d=8), BBB a terrible one (d=0)
        off_rank = lambda c: f.scoring_rank("MLB", c, "offense", 0, DATE, LOCK)[0]
        def_rank = lambda c: f.scoring_rank("MLB", c, "defense", 0, DATE, LOCK)[0]
        for opp in ("HHH", "BBB"):
            c = ctx(home="JJJ", away=opp, pick="JJJ", facts=f)
            gap = def_rank(opp) - off_rank("JJJ")
            self.assertEqual(holds(cond("matchup_edge", who="pick", unit="offense", gap=max(1, gap), n=0), c), gap >= 1)
            self.assertEqual(holds(cond("matchup_edge", who="pick", unit="offense", gap=min(15, gap + 1), n=0), c), False)
        self.assertGreater(def_rank("BBB"), def_rank("HHH"))
        bad = ctx(home="JJJ", away="BBB", pick="JJJ", facts=f)
        self.assertTrue(holds(cond("matchup_edge", who="pick", unit="offense", gap=5, n=0), bad))
        # the reverse unit: BBB's defense (worst) is not better than JJJ's offense rank
        self.assertFalse(holds(cond("matchup_edge", who="opponent", unit="defense", gap=1, n=0), bad))

    def test_games_dated_on_or_after_the_slate_day_never_move_a_rank_or_a_mean(self):
        before = (self.facts.scoring("MLB", "AAA", 0, DATE, LOCK), self.facts.scoring_rank("MLB", "AAA", "offense", 0, DATE, LOCK))
        leak = [{"date": DATE, "start_utc": f"{DATE}T17:00:00Z", "home": "AAA", "away": "BBB", "home_score": 99,
                 "away_score": 0, "game_pk": "leak1"},
                {"date": "2026-10-21", "start_utc": "2026-10-21T17:00:00Z", "home": "AAA", "away": "BBB",
                 "home_score": 99, "away_score": 0, "game_pk": "leak2"}]
        after = FactBook(mlb_games=self.rows + leak)
        self.assertEqual(before, (after.scoring("MLB", "AAA", 0, DATE, LOCK), after.scoring_rank("MLB", "AAA", "offense", 0, DATE, LOCK)))

    def test_nfl_uses_points_and_its_own_season(self):
        rows = []
        for i, home in enumerate(CLUBS):
            away = CLUBS[(i + 1) % 10]
            rows.append({"date": "2026-09-13", "start_utc": "2026-09-13T17:00:00Z", "home": home, "away": away,
                         "home_score": 20 + i, "away_score": 10, "game_pk": f"n{i}"})
        f = FactBook(nfl_games=rows)
        self.assertEqual(f.scoring("NFL", "JJJ", 1, "2026-09-20", LOCK)["pf"], 29)
        self.assertIsNone(f.scoring("NFL", "JJJ", 0, "2026-09-20", LOCK))          # one game is not a season


class ValidationAndMenu(unittest.TestCase):
    def check(self, item, market="moneyline", sports=("MLB",)):
        errors: dict = {}
        out = R.validate_condition(item, kinds=[R.market_kind(market)], markets=[market], sports=list(sports),
                                   path="c", errors=errors)
        return out, errors

    def test_every_new_condition_validates_at_its_defaults_and_renders_a_sentence(self):
        for cid in ("head_to_head", "venue_record", "scoring_rate", "league_rank", "matchup_edge"):
            for sports in (("MLB",), ("NFL",), ("MLB", "NFL")):
                out, errors = self.check(R.default_instance(cid), sports=sports)
                self.assertIsNotNone(out, (cid, sports, errors))
            text = R.condition_text(out, "ml_spread")
            self.assertGreater(len(text), 30, cid)

    def test_out_of_bounds_values_are_refused_not_clamped(self):
        for item in (cond("head_to_head", n=0), cond("head_to_head", n=11), cond("head_to_head", wins=11),
                     cond("head_to_head", window="forever"), cond("head_to_head", n=3, wins=4),
                     cond("venue_record", pct=101), cond("venue_record", ground="neutral"),
                     cond("scoring_rate", n=21), cond("scoring_rate", n=-1), cond("scoring_rate", value=61),
                     cond("scoring_rate", unit="special_teams"), cond("league_rank", places=0),
                     cond("league_rank", places=16), cond("league_rank", end="middle"),
                     cond("matchup_edge", gap=0), cond("matchup_edge", gap=16), cond("matchup_edge", n=2.5)):
            out, errors = self.check(item)
            self.assertIsNone(out, item)
            self.assertTrue(errors, item)

    def test_a_rule_with_each_new_condition_goes_through_the_whole_spec_validator_and_renderer(self):
        for cid in ("head_to_head", "venue_record", "scoring_rate", "league_rank", "matchup_edge"):
            rule = {"label": "", "sports": ["MLB", "NFL"], "markets": ["moneyline"], "side": "either",
                    "price_min": -150, "price_max": 300, "min_books": 3,
                    "when": {"op": "all", "items": [R.default_instance(cid)]}}
            spec = user_spec.validate_spec({"version": 2, "name": "Matchup Dog", "rules": [rule]})
            sentence = render.rule_sentence(spec["rules"][0])
            self.assertIn(R.condition_text(spec["rules"][0]["when"]["items"][0], "ml_spread"), sentence)

    def test_the_menu_lists_them_with_their_bounds_and_a_note_on_the_data_behind_them(self):
        menu = {c["id"]: c for c in user_spec.builder_menu()["conditions"]}
        for cid in ("head_to_head", "venue_record", "scoring_rate", "league_rank", "matchup_edge"):
            self.assertIn(cid, menu)
            self.assertTrue(menu[cid]["available"], cid)
            self.assertEqual(menu[cid]["group"], "Matchups and team strength")
            self.assertGreater(len(menu[cid]["note"]), 40, cid)
            self.assertEqual(menu[cid]["sports"], ["MLB", "NFL"])
        bounds = {p["name"]: p for p in menu["head_to_head"]["params"]}
        self.assertEqual((bounds["n"]["min"], bounds["n"]["max"]), (1, 10))
        self.assertEqual([c["value"] for c in bounds["window"]["choices"]], ["all", "season"])
        self.assertIn("2026", menu["head_to_head"]["note"])           # the held-back stretch is said out loud

    def test_the_translators_menu_carries_them_too(self):
        from src.hounds.english import translate
        ids = {c["id"] for c in translate.translation_menu()["conditions"]}
        self.assertTrue({"head_to_head", "venue_record", "scoring_rate", "league_rank", "matchup_edge"} <= ids)

    def test_evaluating_through_the_tree_tallies_a_missing_fact_by_name(self):
        c = ctx(home="AAA", away="BBB", pick="AAA", facts=FactBook(mlb_games=[]))
        tree = {"op": "all", "items": [cond("head_to_head"), cond("league_rank")]}
        unknown: list = []
        self.assertFalse(R.evaluate_tree(tree, c, unknown))
        self.assertEqual(unknown, ["head_to_head", "league_rank"])


if __name__ == "__main__":
    unittest.main()
