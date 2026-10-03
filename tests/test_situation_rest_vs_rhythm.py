"""src/situation/rest_vs_rhythm.py: the first factor test, reproducible from fixtures.

Nothing here reads the repo's data or a network. The yardstick (log5 with a home edge, the exact
series probability, the exact two-sided test) is checked against independent hand or brute-force
calculations; the pairing against a small world whose every series is known; and the report's
words against the pre-registered rule.
"""

from __future__ import annotations

import json
import math
import unittest
from itertools import product

from src.situation import rest_vs_rhythm as rvr
from tests import situation_fixtures as F


def brute_series(p_by_game, wins_needed=3):
    """The chance of reaching `wins_needed` wins, by playing out ALL the games regardless: a club
    has three wins after five games exactly when it won the first-to-three series."""
    total = 0.0
    for outcome in product((1, 0), repeat=len(p_by_game)):
        prob = 1.0
        for won, p in zip(outcome, p_by_game):
            prob *= p if won else 1.0 - p
        if sum(outcome) >= wins_needed:
            total += prob
    return total


def brute_two_sided(ps, observed):
    """Exact two-sided p by listing every outcome of the independent trials."""
    lower = upper = 0.0
    for outcome in product((1, 0), repeat=len(ps)):
        prob = 1.0
        for won, p in zip(outcome, ps):
            prob *= p if won else 1.0 - p
        if sum(outcome) <= observed:
            lower += prob
        if sum(outcome) >= observed:
            upper += prob
    return min(1.0, 2.0 * min(lower, upper))


class TheYardstick(unittest.TestCase):
    def test_log5_on_paper(self):
        self.assertAlmostEqual(rvr.log5(0.5, 0.5), 0.5)
        self.assertAlmostEqual(rvr.log5(0.6, 0.5), 0.6)                 # against an average club, a club's own rate
        self.assertAlmostEqual(rvr.log5(0.7, 0.3), 0.49 / 0.58, places=9)
        self.assertAlmostEqual(rvr.log5(0.4, 0.6) + rvr.log5(0.6, 0.4), 1.0)
        with self.assertRaises(ValueError):
            rvr.log5(1.0, 0.4)

    def test_the_home_edge_is_applied_to_the_odds(self):
        self.assertAlmostEqual(rvr.with_home_field(0.5, True, 0.54), 0.54)
        self.assertAlmostEqual(rvr.with_home_field(0.5, False, 0.54), 0.46)
        # a 0.6 club at home: odds 1.5 times 0.54/0.46
        odds = 1.5 * (0.54 / 0.46)
        self.assertAlmostEqual(rvr.with_home_field(0.6, True, 0.54), odds / (1 + odds), places=9)
        self.assertAlmostEqual(rvr.with_home_field(0.6, True) + rvr.with_home_field(0.4, False), 1.0)
        # with no edge given, the pre-registered one: two equal clubs, the home club wins 0.53
        self.assertAlmostEqual(rvr.with_home_field(0.5, True), 0.53)
        self.assertAlmostEqual(rvr.with_home_field(0.5, False), 0.47)

    def test_the_series_probability_matches_playing_every_game_out(self):
        pattern = rvr.HOME_PATTERN
        p = [rvr.with_home_field(0.6, home) for home in pattern]
        self.assertAlmostEqual(rvr.series_win_probability(p), brute_series(p), places=12)
        for ps in ([0.5] * 5, [0.9, 0.4, 0.55, 0.3, 0.7], [0.54, 0.54, 0.46, 0.46, 0.54]):
            self.assertAlmostEqual(rvr.series_win_probability(ps), brute_series(ps), places=12)
        self.assertAlmostEqual(rvr.series_win_probability([0.5] * 5), 0.5)

    def test_the_extremes_and_a_best_of_three(self):
        self.assertAlmostEqual(rvr.series_win_probability([1.0] * 5), 1.0)
        self.assertAlmostEqual(rvr.series_win_probability([0.0] * 5), 0.0)
        # first to two of three at 0.6 a game: 0.6^2 + 2 * 0.6^2 * 0.4
        self.assertAlmostEqual(rvr.series_win_probability([0.6] * 3, wins_needed=2), 0.648, places=9)

    def test_too_few_games_cannot_decide_a_series(self):
        with self.assertRaises(ValueError):
            rvr.series_win_probability([0.5, 0.5, 0.5], wins_needed=3)

    def test_the_poisson_binomial_and_the_exact_test(self):
        self.assertEqual(rvr.poisson_binomial_pmf([0.5, 0.5]), [0.25, 0.5, 0.25])
        self.assertAlmostEqual(sum(rvr.poisson_binomial_pmf([0.3, 0.8, 0.55, 0.1])), 1.0)
        self.assertAlmostEqual(rvr.two_sided_p([0.5, 0.5], 2), 0.5)
        self.assertAlmostEqual(rvr.two_sided_p([0.5, 0.5], 1), 1.0)
        self.assertAlmostEqual(rvr.two_sided_p([0.9, 0.9, 0.9], 0), 0.002, places=9)
        for ps, k in (([0.6, 0.7, 0.55, 0.4, 0.65], 1), ([0.6, 0.7, 0.55, 0.4, 0.65], 5), ([0.2, 0.3], 0)):
            self.assertAlmostEqual(rvr.two_sided_p(ps, k), brute_two_sided(ps, k), places=12)

    def test_shrinking_pulls_both_clubs_toward_one_half(self):
        self.assertAlmostEqual(rvr._shrunk(0.6, 0.5), 0.55)
        self.assertAlmostEqual(rvr._shrunk(0.4, 0.5), 0.45)
        self.assertEqual(rvr._shrunk(0.6, 0.0), 0.6)
        pair = {"bye_win_pct": 0.65, "played_win_pct": 0.45, "g1_bye_home": True}
        self.assertLess(rvr.expected_for(pair, shrink=0.5)["p_series"], rvr.expected_for(pair)["p_series"])

    def test_the_constants_are_the_pre_registered_ones(self):
        self.assertEqual(rvr.HOME_FIELD_WIN_RATE, 0.53)
        self.assertEqual(rvr.HOME_PATTERN, (True, True, False, False, True))
        self.assertEqual((rvr.FIRST_SEASON, rvr.LAST_SEASON), (2015, 2025))
        self.assertAlmostEqual(rvr.SENSITIVITY_SHRINK, 1 / 3)
        self.assertEqual(rvr.SIGNIFICANCE, 0.05)


class TheRecords(unittest.TestCase):
    def test_regular_season_records_from_games(self):
        rec = rvr.records_from_games(F.world())
        self.assertEqual(rec[(2025, "NYY")], {"wins": 9, "losses": 6})
        self.assertEqual(rec[(2025, "TB")], {"wins": 5, "losses": 9})
        self.assertEqual(rec[(2025, "BOS")], {"wins": 3, "losses": 2})
        self.assertNotIn((2025, "LAD"), rec)                      # postseason games are not a regular season

    def test_a_duplicate_game_counts_once_and_a_tie_not_at_all(self):
        rows = F.regular_season() + [dict(F.regular_season()[0])] + [F.g(7, "2025-09-01", "NYY", "BOS", 3, 3)]
        self.assertEqual(rvr.records_from_games(rows)[(2025, "NYY")], {"wins": 9, "losses": 6})

    def test_a_club_spelled_two_ways_is_one_club(self):
        rows = [F.g(1, "2024-05-01", "OAK", "NYY", 2, 1), F.g(2, "2025-05-01", "ATH", "NYY", 3, 1)]
        rec = rvr.records_from_games(rows)
        self.assertEqual(rec[(2024, "OAK")], {"wins": 1, "losses": 0})
        self.assertEqual(rec[(2025, "OAK")], {"wins": 1, "losses": 0})


class ThePairing(unittest.TestCase):
    def setUp(self):
        self.records = rvr.records_from_games(F.world())

    def test_a_bye_against_a_club_that_played_qualifies_with_its_facts(self):
        pairs, excluded = rvr.qualifying_series(F.world(), self.records, seasons=(2025,))
        self.assertEqual((len(pairs), excluded), (1, []))
        p = pairs[0]
        self.assertEqual((p["bye"], p["played"], p["season"]), ("NYY", "TB", 2025))
        self.assertAlmostEqual(p["bye_win_pct"], 0.6)
        self.assertAlmostEqual(p["played_win_pct"], 5 / 14)
        self.assertIs(p["g1_bye_home"], True)
        self.assertIs(p["bye_won_g1"], True)                       # NYY 5, TB 2 on 2025-10-04
        self.assertEqual(p["g1_score"], {"TB": 2, "NYY": 5})
        self.assertIs(p["bye_won_series"], True)
        self.assertEqual((p["series_score"], p["series_games"]), ({"NYY": 3, "TB": 2}, 5))
        self.assertEqual(p["played_round"], {"won": True, "games": 3, "score": {"BOS": 1, "TB": 2},
                                             "ended": "2025-10-02", "opponent": "BOS"})

    def test_a_series_between_two_rested_clubs_is_left_out_and_listed(self):
        rows = F.world() + [F.g(500 + i, f"2025-10-0{4 + i}", "HOU", "CLE", 3, 1, "D") for i in range(3)]
        pairs, excluded = rvr.qualifying_series(rows, self.records, seasons=(2025,))
        self.assertEqual(len(pairs), 1)
        self.assertEqual([(e["series"], e["reason"]) for e in excluded], [("2025 CLE-HOU", "both_rested")])

    def test_a_series_between_two_clubs_that_played_is_left_out(self):
        rows = F.world() + [F.g(600 + i, f"2025-10-0{4 + i}", "SEA", "TOR", 3, 1, "D") for i in range(3)]
        pairs, excluded = rvr.qualifying_series(rows, self.records, seasons=(2025,))
        self.assertEqual([e["reason"] for e in excluded], ["both_played"])

    def test_an_open_series_is_left_out(self):
        rows = F.world() + [F.g(700, "2025-10-04", "PIT", "STL", 3, 1, "D"), F.g(701, "2025-10-05", "PIT", "STL", 2, 4, "D")]
        records = {**self.records, (2025, "PIT"): {"wins": 80, "losses": 82}, (2025, "STL"): {"wins": 82, "losses": 80}}
        pairs, excluded = rvr.qualifying_series(rows, records, seasons=(2025,))
        self.assertIn({"series": "2025 PIT-STL", "season": 2025, "reason": "series_open"}, excluded)

    def test_a_club_with_no_record_is_left_out_not_guessed(self):
        records = {k: v for k, v in self.records.items() if k != (2025, "TB")}
        pairs, excluded = rvr.qualifying_series(F.world(), records, seasons=(2025,))
        self.assertEqual((pairs, [e["reason"] for e in excluded]), ([], ["no_record"]))

    def test_a_season_with_no_wild_card_round_in_the_data_is_unknown_not_rested(self):
        rows = [r for r in F.world() if r["game_type"] != "F"]
        pairs, excluded = rvr.qualifying_series(rows, self.records, seasons=(2025,))
        self.assertEqual((pairs, [e["reason"] for e in excluded]), ([], ["round_incomplete"]))

    def test_2020_had_no_byes_so_it_has_no_contrast(self):
        rows = []
        pk = 1
        for a, b in (("A", "B"), ("C", "D"), ("E", "F"), ("G", "H"), ("I", "J"), ("K", "L"), ("M", "N"), ("O", "P")):
            rows += [F.g(pk, "2020-09-29", a, b, 3, 1, "F"), F.g(pk + 1, "2020-09-30", a, b, 2, 1, "F")]
            pk += 2
        for pair in (("A", "C"), ("E", "G"), ("I", "K"), ("M", "O")):
            rows += [F.g(pk + i, f"2020-10-0{5 + i}", pair[0], pair[1], 4, 2, "D") for i in range(3)]
            pk += 3
        records = {(2020, t): {"wins": 30, "losses": 30} for t in "ABCDEFGHIJKLMNOP"}
        pairs, excluded = rvr.qualifying_series(rows, records, seasons=(2020,))
        self.assertEqual(pairs, [])
        self.assertEqual([e["reason"] for e in excluded], ["both_played"] * 4)

    def test_only_the_seasons_asked_for_are_read(self):
        pairs, excluded = rvr.qualifying_series(F.world(), self.records, seasons=(2024,))
        self.assertEqual((pairs, excluded), ([], []))


class TheExpectation(unittest.TestCase):
    def test_the_fixture_series_by_independent_arithmetic(self):
        pairs, _ = rvr.qualifying_series(F.world(), rvr.records_from_games(F.world()), seasons=(2025,))
        pa, pb = 0.6, 5 / 14
        neutral = (pa - pa * pb) / (pa + pb - 2 * pa * pb)            # log5, written out
        edge = 0.53 / 0.47                                             # the pre-registered home edge, on the odds
        home_odds, away_odds = neutral / (1 - neutral) * edge, neutral / (1 - neutral) / edge
        p_home, p_away = home_odds / (1 + home_odds), away_odds / (1 + away_odds)
        exp = rvr.expected_for(pairs[0])
        self.assertAlmostEqual(exp["neutral"], neutral, places=9)
        self.assertAlmostEqual(exp["p_game_1"], p_home, places=9)
        self.assertEqual([round(x, 9) for x in exp["p_games"]],
                         [round(x, 9) for x in (p_home, p_home, p_away, p_away, p_home)])
        self.assertAlmostEqual(exp["p_series"], brute_series([p_home, p_home, p_away, p_away, p_home]), places=9)
        self.assertGreater(exp["p_game_1"], 0.7)            # the bye club is the much better club on paper

    def test_a_bye_club_that_did_not_host_game_one_gets_the_other_home_pattern(self):
        pair = {"bye_win_pct": 0.5, "played_win_pct": 0.5, "g1_bye_home": False}
        exp = rvr.expected_for(pair)
        self.assertAlmostEqual(exp["p_game_1"], 1 - rvr.HOME_FIELD_WIN_RATE)       # on the road in game 1


def synthetic_world():
    """Two seasons, six bye-against-played series between equal clubs (every record .500), with the
    outcomes chosen by hand. 2019 is a single-game Wild Card (two of them); 2024 is the best-of-three
    round (four of them). A spec is (bye club, club that played, its Wild Card opponent, the winners
    of the Division Series games, 'b' for the bye club and 'p' for the other)."""
    rows, records, pk = [], {}, 1000
    specs = {2019: [("AA", "BB", "CC", "bbb"), ("DD", "EE", "FF", "pbpp")],
             2024: [("A1", "P1", "O1", "bbb"), ("A2", "P2", "O2", "ppp"), ("A3", "P3", "O3", "bpbb"),
                    ("A4", "P4", "O4", "pbbpp")]}
    for season, items in specs.items():
        for bye, played, opp, winners in items:
            records[(season, bye)] = records[(season, played)] = records[(season, opp)] = {"wins": 81, "losses": 81}
            if season == 2019:
                rows.append(F.g(pk, f"{season}-10-02", opp, played, 1, 3, "F"))
                pk += 1
            else:
                rows += [F.g(pk, f"{season}-10-01", opp, played, 1, 3, "F"), F.g(pk + 1, f"{season}-10-02", opp, played, 2, 5, "F")]
                pk += 2
            hosts = [bye, bye, played, played, bye]
            for i, w in enumerate(winners):
                home = hosts[i]
                away = played if home == bye else bye
                bye_wins = w == "b"
                home_score, away_score = (4, 2) if (home == bye) == bye_wins else (2, 4)
                rows.append(F.g(pk, f"{season}-10-{5 + i:02d}", away, home, away_score, home_score, "D"))
                pk += 1
    return rows, records


class TheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, records = synthetic_world()
        cls.result = rvr.run(rows, records, seasons=(2019, 2020, 2024))
        cls.s = cls.result["summary"]

    def test_the_six_series_and_what_happened_in_each(self):
        self.assertEqual(self.s["n_series"], 6)
        self.assertEqual(self.s["game_1"]["observed"], 3)       # bye club won G1 in AA, A1, A3
        self.assertEqual(self.s["series"]["observed"], 3)       # and the series in AA, A1, A3
        self.assertEqual(self.s["by_season"], {2019: {"series": 2, "bye_g1_wins": 1, "bye_series_wins": 1},
                                               2024: {"series": 4, "bye_g1_wins": 2, "bye_series_wins": 2}})

    def test_equal_clubs_leave_only_the_home_edge_for_game_one(self):
        g1, h = self.s["game_1"], 0.53
        self.assertEqual(g1["n"], 6)
        self.assertAlmostEqual(g1["expected"], 6 * h, places=3)
        self.assertEqual(g1["excess"], round(3 - 6 * h, 3))
        self.assertAlmostEqual(g1["p_two_sided"], round(brute_two_sided([h] * 6, 3), 4), places=4)

    def test_the_series_expectation_is_the_home_pattern_summed_over_six_series(self):
        s, h = self.s["series"], 0.53
        each = brute_series([h, h, 1 - h, 1 - h, h])
        self.assertAlmostEqual(s["expected"], 6 * each, places=3)
        self.assertAlmostEqual(s["p_two_sided"], round(brute_two_sided([each] * 6, 3), 4), places=4)
        self.assertEqual(s["excess_points"], round(100 * (3 - 6 * each) / 6, 2))

    def test_the_standard_deviation_and_the_swing_it_could_see(self):
        s = self.s["game_1"]
        sd = math.sqrt(6 * 0.53 * 0.47)
        self.assertEqual(s["sd_wins"], round(sd, 3))
        self.assertEqual(s["detectable_points"], round(100 * 1.96 * sd / 6, 1))

    def test_a_season_with_no_series_is_named(self):
        self.assertEqual(self.result["seasons_without"], [2020])
        self.assertEqual(self.result["seasons_with_series"], [2019, 2024])

    def test_no_price_is_invented(self):
        p = self.s["prices"]
        self.assertEqual((p["series_with_a_price"], p["of"]), (0, 6))
        self.assertIn("2026 only", p["note"])
        self.assertTrue(all(r["price"] is None for r in self.result["series"]))

    def test_a_supplied_price_is_joined_to_its_game_one(self):
        rows, records = synthetic_world()
        pairs, _ = rvr.qualifying_series(rows, records, seasons=(2019, 2024))
        pk = pairs[0]["g1_game_pk"]
        out = rvr.evaluate(pairs, prices={pk: {"bye_moneyline": -150, "played_moneyline": 130}})
        self.assertEqual(out["summary"]["prices"]["series_with_a_price"], 1)
        self.assertEqual(out["series"][0]["price"], {"bye_moneyline": -150, "played_moneyline": 130})
        self.assertIsNone(out["series"][1]["price"])

    def test_the_sensitivity_run_exists_and_changes_nothing_when_clubs_are_equal(self):
        sens = self.result["sensitivity"]
        self.assertAlmostEqual(sens["shrink_toward_500"], 0.3333)
        self.assertEqual(sens["game_1"]["expected"], self.s["game_1"]["expected"])     # .500 clubs do not move

    def test_it_is_deterministic_and_json_clean(self):
        rows, records = synthetic_world()
        again = rvr.run(rows, records, seasons=(2019, 2020, 2024))
        self.assertEqual(json.dumps(again, sort_keys=True, default=str),
                         json.dumps(self.result, sort_keys=True, default=str))
        rows.reverse()
        self.assertEqual(json.dumps(rvr.run(rows, records, seasons=(2019, 2020, 2024)), sort_keys=True, default=str),
                         json.dumps(self.result, sort_keys=True, default=str))


class TheVerdict(unittest.TestCase):
    def test_a_significant_shortfall_is_reported_in_its_direction(self):
        text = rvr.verdict({"series": {"n": 28, "observed": 10, "expected": 17.2, "excess": -7.2,
                                       "p_two_sided": 0.01, "detectable_points": 17.9}})
        self.assertIn("fewer series", text)
        self.assertIn("10 against 17.2 expected over 28", text)
        self.assertNotIn("null", text.lower())

    def test_a_significant_surplus_is_reported_as_more(self):
        text = rvr.verdict({"series": {"n": 28, "observed": 24, "expected": 17.2, "excess": 6.8,
                                       "p_two_sided": 0.02, "detectable_points": 17.9}})
        self.assertIn("more series", text)

    def test_anything_else_is_a_null_that_says_how_big_an_effect_it_could_see(self):
        text = rvr.verdict({"series": {"n": 28, "observed": 14, "expected": 17.2, "excess": -3.2,
                                       "p_two_sided": 0.2, "detectable_points": 17.9}})
        self.assertTrue(text.startswith("A null result"))
        self.assertIn("about 17.9 points a series", text)
        self.assertIn("cannot rule out a smaller effect in either direction", text)

    def test_the_bar_is_point_zero_five_exactly(self):
        base = {"n": 28, "observed": 12, "expected": 17.2, "excess": -5.2, "detectable_points": 17.9}
        self.assertIn("null", rvr.verdict({"series": dict(base, p_two_sided=0.05)}).lower())
        self.assertIn("fewer", rvr.verdict({"series": dict(base, p_two_sided=0.0499)}))

    def test_no_series_is_no_result(self):
        self.assertIn("no result", rvr.verdict({"series": {"n": 0}}))


class TheWords(unittest.TestCase):
    def setUp(self):
        rows, records = synthetic_world()
        self.result = rvr.run(rows, records, seasons=(2019, 2024))

    def test_the_markdown_table_has_a_row_per_series(self):
        lines = rvr.render_markdown_table(self.result)
        self.assertEqual(len(lines), 2 + 6)
        self.assertTrue(lines[0].startswith("| Season | Bye club"))
        self.assertIn("won its Wild Card game", lines[2])        # 2019 was a single game
        self.assertIn("won the Wild Card Series 2-0", lines[4])   # 2024 was a best-of-three
        self.assertIn("| none |", lines[2])

    def test_the_text_report_states_the_numbers_the_price_gap_and_the_verdict(self):
        text = "\n".join(rvr.render_text(self.result))
        self.assertIn("6 series with one club on a bye", text)
        self.assertIn("Game 1: the bye club won 3 of 6", text)
        self.assertIn("Price: 0 of 6 series have one", text)
        self.assertIn("2026 only", text)
        self.assertIn("Sensitivity", text)
        self.assertIn(self.result["verdict"], text)


if __name__ == "__main__":
    unittest.main()
