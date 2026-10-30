"""NHL live game state (src/sports/live_state/nhl.py): derivation from the REAL 2026-10-29 captures, the situation codes,
the intermission, the "unknown is None" rule for every derived field, the one-line text, and the per-pass request cap.

No network: every fetch is a function over tests/fixtures/live_state/ (see tests/live_state_support.py).
"""
from __future__ import annotations

import copy
import unittest
from datetime import timedelta

from src.sports.live_state import lines, nhl, store
from tests import live_state_support as S


def base_of(doc_games, gid):
    return next(b for b in nhl.parse_score_now(doc_games) if b["game_id"] == gid)


class TheScoreRead(unittest.TestCase):
    def setUp(self):
        self.games = {b["game_id"]: b for b in nhl.parse_score_now(S.load("nhl_score_now.json"))}

    def test_every_game_of_the_day_is_read_with_its_state_word(self):
        self.assertEqual({g: b["state"] for g, b in self.games.items()},
                         {"2026020213": "live", "2026020211": "live", "2026020212": "live", "2026020208": "final", "2026020205": "final"})

    def test_a_live_game_carries_period_clock_score_and_shots(self):
        g = self.games[S.GAME]
        self.assertEqual((g["period"], g["period_type"], g["period_label"]), (2, "REG", "2nd"))
        self.assertEqual((g["clock"], g["seconds_remaining"], g["clock_running"], g["in_intermission"]), ("16:19", 979, True, False))
        self.assertEqual((g["away"]["abbrev"], g["away"]["score"], g["away"]["sog"]), ("VAN", 1, 12))
        self.assertEqual((g["home"]["abbrev"], g["home"]["score"], g["home"]["sog"]), ("SJS", 0, 8))
        self.assertEqual(g["start_utc"], "2026-10-30T02:00:00Z")

    def test_the_score_read_names_a_club_from_its_place_table_and_nickname(self):
        # the score read carries only "Sharks"; the full name a book uses ("San Jose Sharks") comes from the abbreviation's place
        self.assertEqual((self.games[S.GAME]["home"]["name"], self.games[S.GAME]["away"]["name"]), ("San Jose Sharks", "Vancouver Canucks"))
        self.assertEqual(self.games["2026020212"]["home"]["name"], "Los Angeles Kings")

    def test_an_intermission_is_flagged_and_a_final_has_no_clock(self):
        self.assertTrue(self.games[S.INTERMISSION_GAME]["in_intermission"])
        done = self.games["2026020205"]
        self.assertIsNone(done["clock"])
        self.assertEqual((done["period"], done["period_label"], done["period_type"]), (4, "OT", "OT"))

    def test_period_labels(self):
        self.assertEqual([nhl.period_label(n, t, 3) for n, t in ((1, "REG"), (2, "REG"), (3, "REG"), (4, "OT"), (5, "OT"), (5, "SO"))],
                         ["1st", "2nd", "3rd", "OT", "2OT", "SO"])
        self.assertIsNone(nhl.period_label(None, "REG", 3))
        self.assertIsNone(nhl.period_label(0, "REG", 3))

    def test_a_postponed_game_is_not_live(self):
        self.assertEqual(nhl.state_word("FUT", "PPD"), "postponed")
        self.assertEqual(nhl.state_word("LIVE", "OK"), "live")
        self.assertEqual(nhl.state_word("CRIT", "OK"), "live")
        self.assertEqual(nhl.state_word("OFF", "OK"), "final")
        self.assertIsNone(nhl.state_word("???", "OK"))

    def test_an_unreadable_game_is_left_out_not_guessed(self):
        self.assertEqual(nhl.parse_score_now({"games": [{"id": 1}, {"awayTeam": {}, "homeTeam": {}}, "junk"]}), [])
        self.assertEqual(nhl.parse_score_now({}), [])


class TheSituationCode(unittest.TestCase):
    def test_even_strength_five_on_five(self):
        s = nhl.strength_from_code("1551")
        self.assertEqual((s["away_skaters"], s["home_skaters"], s["pp_side"], s["pp_matchup"], s["empty_net"]), (5, 5, None, None, None))

    def test_home_on_a_power_play_when_away_is_a_man_down(self):                # 5v4, the code the intermission fixture carries
        s = nhl.strength_from_code("1451")
        self.assertEqual((s["pp_side"], s["pp_matchup"], s["empty_net"]), ("home", "5v4", None))

    def test_away_on_a_power_play_when_home_is_a_man_down(self):
        s = nhl.strength_from_code("1541")
        self.assertEqual((s["pp_side"], s["pp_matchup"]), ("away", "5v4"))

    def test_a_pulled_goalie_with_a_sixth_skater_is_an_empty_net_not_a_power_play(self):    # 6v5
        s = nhl.strength_from_code("0651")
        self.assertEqual((s["empty_net"], s["pp_side"], s["pp_matchup"]), ("away", None, None))
        s = nhl.strength_from_code("1560")
        self.assertEqual((s["empty_net"], s["pp_side"]), ("home", None))

    def test_a_pulled_goalie_while_the_other_side_is_short_is_both(self):       # 6v4: the extra attacker is not the advantage, the penalty is
        s = nhl.strength_from_code("0641")
        self.assertEqual((s["empty_net"], s["pp_side"], s["pp_matchup"]), ("away", "away", "5v4"))

    def test_three_on_three_and_a_two_man_advantage(self):
        self.assertIsNone(nhl.strength_from_code("1331")["pp_side"])
        s = nhl.strength_from_code("1531")
        self.assertEqual((s["pp_side"], s["pp_matchup"]), ("away", "5v3"))

    def test_a_code_that_cannot_be_right_is_unknown(self):
        for bad in (None, "", "155", "15511", "abcd", "2551", "1552", "0660", "1010", "1251", "1771", "1121", 1551.5, "1 51"):
            with self.subTest(code=bad):
                self.assertIsNone(nhl.strength_from_code(bad))

    def test_an_integer_code_is_read_like_its_text(self):
        self.assertEqual(nhl.strength_from_code(1451)["pp_side"], "home")


class TheDetailFromTheCaptures(unittest.TestCase):
    def setUp(self):
        self.detail = nhl.derive_detail(S.box(), S.pbp())

    def test_even_strength_from_the_latest_play(self):
        s = self.detail["strength"]
        self.assertEqual((s["code"], s["pp_side"], s["empty_net"], s["as_of_period"], s["as_of_time_remaining"]), ("1551", None, None, 2, "16:27"))

    def test_the_goalie_in_net_comes_from_the_latest_shot_against_each_team(self):
        g = self.detail["goalies"]
        self.assertEqual((g["home"]["id"], g["home"]["name"], g["home"]["saves"], g["home"]["shots_against"], g["home"]["save_pct"]),
                         (8482137, "Y. Askarov", 11, 12, 0.917))
        self.assertEqual((g["away"]["id"], g["away"]["saves"], g["away"]["shots_against"], g["away"]["save_pct"]), (8482447, 8, 8, 1.0))

    def test_skaters_carry_tonights_numbers(self):
        away = {s["id"]: s for s in self.detail["skaters"]["away"]}
        self.assertEqual(len(away), 18)                                          # 12 forwards and 6 defensemen
        oc = away[8482055]
        self.assertEqual((oc["name"], oc["pos"], oc["g"], oc["a"], oc["p"], oc["sog"], oc["toi_s"]), ("D. O'Connor", "L", 1, 0, 1, 4, 421))
        self.assertEqual(away[8480012]["a"], 1)
        self.assertEqual(sum(s["g"] for s in self.detail["skaters"]["away"]), 1)

    def test_goals_by_period_add_up_to_the_document_score(self):
        self.assertEqual(self.detail["goals_by_period"], [{"period": 1, "type": "REG", "away": 1, "home": 0},
                                                           {"period": 2, "type": "REG", "away": 0, "home": 0}])

    def test_full_names_come_from_place_plus_common_name(self):
        self.assertEqual(self.detail["names"], {"home": "San Jose Sharks", "away": "Vancouver Canucks"})

    def test_the_intermission_game_has_no_strength_but_keeps_everything_else(self):
        d = nhl.derive_detail(S.box(S.INTERMISSION_GAME), S.pbp(S.INTERMISSION_GAME))
        self.assertIsNone(d["strength"])                                         # the period-end play says 5v5 but nobody is skating
        self.assertEqual(d["goals_by_period"], [{"period": 1, "type": "REG", "away": 3, "home": 3}])
        self.assertEqual(d["goalies"]["away"]["name"], "C. Ellis")


class StrengthIsOnlyEverTheLatestPlaysCode(unittest.TestCase):
    def strength(self, doc):
        return nhl.derive_detail(S.box(), doc)["strength"]

    def test_the_latest_play_by_sort_order_decides_not_list_position(self):
        doc = S.with_code(S.pbp(), "1451")
        doc["plays"].reverse()                                                   # the list order must not matter
        self.assertEqual(self.strength(doc)["pp_side"], "home")

    def test_each_case_through_a_whole_document(self):
        for code, pp, empty in (("1551", None, None), ("1451", "home", None), ("1541", "away", None), ("0651", None, "away"),
                                ("1560", None, "home"), ("0641", "away", "away")):
            with self.subTest(code=code):
                s = self.strength(S.with_code(S.pbp(), code))
                self.assertEqual((s["pp_side"], s["empty_net"]), (pp, empty))

    def test_an_unreadable_latest_code_is_unknown(self):
        self.assertIsNone(self.strength(S.with_code(S.pbp(), "9999")))
        doc = S.with_play(S.pbp())
        del doc["plays"][-1]["situationCode"]
        self.assertIsNone(self.strength(doc))

    def test_a_play_far_behind_the_clock_could_be_a_power_play_that_ended_so_it_is_unknown(self):
        doc = S.with_code(S.pbp(), "1451", timeRemaining="19:00")               # the clock reads 16:19: 161 seconds later
        self.assertIsNone(self.strength(doc))
        doc = S.with_code(S.pbp(), "1451", timeRemaining="17:20")               # 61 seconds: inside the allowance
        self.assertEqual(self.strength(doc)["pp_side"], "home")

    def test_a_play_from_another_period_is_unknown(self):
        doc = S.with_code(S.pbp(), "1451")
        doc["plays"][-1]["periodDescriptor"] = {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3}
        self.assertIsNone(self.strength(doc))

    def test_a_shootout_has_no_strength(self):
        doc = S.with_code(S.pbp(), "1010")
        doc["periodDescriptor"]["periodType"] = "SO"
        self.assertIsNone(self.strength(doc))

    def test_no_plays_is_unknown(self):
        doc = S.pbp()
        doc["plays"] = []
        self.assertIsNone(self.strength(doc))


class TheGoalieInNet(unittest.TestCase):
    def goalies(self, doc, strength=None):
        return nhl.goalies_in_net(S.box(), doc["plays"], strength)

    def test_an_empty_net_shot_leaves_the_goalie_unknown(self):
        shot = dict(typeDescKey="shot-on-goal", details={"eventOwnerTeamId": 23, "shootingPlayerId": 1})   # VAN shoots at SJS: no goalieInNetId
        doc = S.with_play(S.pbp(), **shot)
        self.assertIsNone(self.goalies(doc)["home"])
        self.assertEqual(self.goalies(doc)["away"]["name"], "L. Meriläinen")

    def test_a_goalie_id_that_is_not_on_that_teams_roster_is_unknown_never_placed(self):
        doc = S.with_play(S.pbp(), typeDescKey="shot-on-goal", details={"eventOwnerTeamId": 23, "goalieInNetId": 8482447})
        # 8482447 is VAN's goalie, and the shot was VAN's: it cannot be SJS's goalie in net
        self.assertIsNone(self.goalies(doc)["home"])

    def test_the_latest_shot_not_the_first_names_the_goalie(self):
        doc = S.pbp()
        starter = doc["plays"][0]
        self.assertEqual(self.goalies(doc)["home"]["id"], 8482137)
        backup = next(g for g in S.box()["playerByGameStats"]["homeTeam"]["goalies"] if g["playerId"] != 8482137)
        doc = S.with_play(doc, typeDescKey="shot-on-goal", details={"eventOwnerTeamId": 23, "goalieInNetId": backup["playerId"]})
        self.assertEqual(self.goalies(doc)["home"]["id"], backup["playerId"])      # the backup came in: the latest shot says so
        self.assertIsNotNone(starter)

    def test_a_net_the_situation_says_is_empty_has_no_goalie(self):
        strength = nhl.strength_from_code("1560")
        self.assertIsNone(self.goalies(S.pbp(), strength)["home"])
        self.assertIsNotNone(self.goalies(S.pbp(), strength)["away"])

    def test_before_any_shot_the_goalie_with_the_ice_time_is_in_net(self):
        doc = S.pbp()
        doc["plays"] = [p for p in doc["plays"] if p["typeDescKey"] not in ("shot-on-goal", "goal")]
        g = self.goalies(doc)
        self.assertEqual((g["home"]["name"], g["away"]["name"]), ("Y. Askarov", "L. Meriläinen"))

    def test_two_goalies_level_on_ice_time_before_any_shot_is_unknown(self):
        doc, bx = S.pbp(), S.box()
        doc["plays"] = [p for p in doc["plays"] if p["typeDescKey"] not in ("shot-on-goal", "goal")]
        for g in bx["playerByGameStats"]["homeTeam"]["goalies"]:
            g["toi"] = "10:00"
        self.assertIsNone(nhl.goalies_in_net(bx, doc["plays"], None)["home"])

    def test_a_goalie_who_has_not_played_is_not_in_net(self):
        doc, bx = S.pbp(), S.box()
        doc["plays"] = [p for p in doc["plays"] if p["typeDescKey"] not in ("shot-on-goal", "goal")]
        for side in ("homeTeam", "awayTeam"):
            for g in bx["playerByGameStats"][side]["goalies"]:
                g["toi"] = "00:00"
        self.assertEqual(nhl.goalies_in_net(bx, doc["plays"], None), {"home": None, "away": None})

    def test_save_percentage_is_none_before_the_first_shot_faced(self):
        self.assertIsNone(nhl._goalie_row({"playerId": 1, "name": {"default": "X"}, "saves": 0, "shotsAgainst": 0})["save_pct"])


class GoalsByPeriod(unittest.TestCase):
    def test_a_goal_the_score_does_not_know_about_makes_the_whole_list_unknown(self):
        doc = S.pbp()
        doc["awayTeam"]["score"] = 2                                            # the document says 2-0, its goal events say 1-0
        self.assertIsNone(nhl.goals_by_period(doc))

    def test_overtime_goals_are_counted_in_their_own_period(self):
        doc = S.pbp()
        doc["periodDescriptor"] = {"number": 4, "periodType": "OT", "maxRegulationPeriods": 3}
        goal = {"eventId": 900, "sortOrder": 900, "periodDescriptor": {"number": 4, "periodType": "OT", "maxRegulationPeriods": 3},
                "typeDescKey": "goal", "details": {"eventOwnerTeamId": 28}}
        doc["plays"].append(goal)
        doc["homeTeam"]["score"] = 1
        rows = nhl.goals_by_period(doc)
        self.assertEqual([(r["period"], r["type"], r["away"], r["home"]) for r in rows],
                         [(1, "REG", 1, 0), (2, "REG", 0, 0), (3, "REG", 0, 0), (4, "OT", 0, 1)])

    def test_shootout_attempts_are_not_goals(self):
        doc = S.pbp()
        doc["plays"].append({"eventId": 901, "sortOrder": 901, "periodDescriptor": {"number": 5, "periodType": "SO", "maxRegulationPeriods": 3},
                             "typeDescKey": "goal", "details": {"eventOwnerTeamId": 28}})
        self.assertIsNotNone(nhl.goals_by_period(doc))


class TheLine(unittest.TestCase):
    def state(self, **over):
        base = base_of(S.load("nhl_score_now.json"), S.GAME)
        base.update(strength=None, goalies=None, skaters=None, goals_by_period=None)
        base.update(over)
        return base

    def test_a_game_in_play_reads_period_clock_and_shots_away_then_home(self):
        self.assertEqual(lines.nhl_line(self.state()), "2nd · 16:19 · SOG 12-8")

    def test_the_example_from_the_brief(self):
        st = self.state(clock="8:14", away={"abbrev": "WSH", "name": "Washington Capitals", "score": 1, "sog": 18},
                        home={"abbrev": "NYR", "name": "New York Rangers", "score": 2, "sog": 11},
                        strength=nhl.strength_from_code("1541"))
        self.assertEqual(lines.nhl_line(st), "2nd · 8:14 · SOG 18-11 · PP WSH")

    def test_a_home_power_play_and_an_empty_net_name_the_team(self):
        st = self.state(strength=nhl.strength_from_code("1451"))
        self.assertTrue(lines.nhl_line(st).endswith("PP SJS"))
        st = self.state(strength=nhl.strength_from_code("0651"))
        self.assertTrue(lines.nhl_line(st).endswith("empty net VAN"))
        st = self.state(strength=nhl.strength_from_code("0641"))
        self.assertTrue(lines.nhl_line(st).endswith("PP VAN · empty net VAN"))

    def test_an_intermission_says_so_and_nothing_else(self):
        self.assertEqual(lines.nhl_line(self.state(in_intermission=True, period=1, period_label="1st")), "1st intermission")

    def test_an_unknown_part_is_left_out_not_filled_in(self):
        st = self.state()
        st["away"] = dict(st["away"], sog=None)
        self.assertEqual(lines.nhl_line(st), "2nd · 16:19")
        st["clock"] = None
        self.assertEqual(lines.nhl_line(st), "2nd")

    def test_overtime_and_a_shootout(self):
        self.assertEqual(lines.nhl_line(self.state(period=4, period_type="OT", period_label="OT", clock="3:02")), "OT · 3:02 · SOG 12-8")
        self.assertEqual(lines.nhl_line(self.state(period=5, period_type="SO", period_label="SO", clock="0:00")), "SO · SOG 12-8")

    def test_a_game_that_is_not_live_has_no_line(self):
        self.assertIsNone(lines.nhl_line(self.state(state="final")))
        self.assertIsNone(lines.nhl_line(self.state(period_label=None)))
        self.assertIsNone(lines.line_for(None))
        self.assertIsNone(lines.line_for({"sport": "CRICKET"}))

    def test_no_line_uses_edge_lock_beta_new_or_bet_wording(self):
        import re
        for code in ("1551", "1451", "1541", "0651", "0641", "1331"):
            for im in (False, True):
                text = lines.nhl_line(self.state(strength=nhl.strength_from_code(code), in_intermission=im))
                self.assertIsNone(re.search(r"(?i)(edge|lock|beta|new|bet|wager|pick)", text), text)


class OnePassOverTheFixtures(unittest.TestCase):
    def setUp(self):
        store.clear()
        self.addCleanup(store.clear)
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            return S.fixture_fetch(url)
        self.fetch = fetch

    def test_a_pass_reads_the_score_once_then_box_and_play_by_play_for_live_games_with_fixtures(self):
        report = nhl.fetch_and_store(S.NOW, self.fetch)
        self.assertEqual(self.calls[0], nhl.SCORE_URL)
        self.assertEqual(report["games"], 5)
        self.assertEqual(report["live"], 3)
        self.assertEqual(sorted(report["detail_ok"]), sorted([S.GAME, S.INTERMISSION_GAME]))
        self.assertEqual(report["detail_failed"], ["2026020212"])               # no capture for this one: it fails alone, the others stand
        view = store.get("NHL", S.GAME, S.NOW)
        self.assertEqual(view["strength"]["code"], "1551")
        self.assertEqual(view["home"]["name"], "San Jose Sharks")
        self.assertIsNone(store.get("NHL", "2026020212", S.NOW)["strength"])     # and it claims nothing it has not read

    def test_detail_is_read_at_most_every_sixty_seconds(self):
        nhl.fetch_and_store(S.NOW, self.fetch)
        self.calls.clear()
        nhl.fetch_and_store(S.at(30), self.fetch)
        self.assertEqual([u for u in self.calls if "gamecenter" in u and (S.GAME in u or S.INTERMISSION_GAME in u)], [])
        self.calls.clear()
        nhl.fetch_and_store(S.at(61), self.fetch)
        self.assertTrue(any(S.GAME in u for u in self.calls))

    def test_the_request_cap_bounds_a_pass_and_the_oldest_read_goes_first(self):
        doc = S.load("nhl_score_now.json")
        template = next(g for g in doc["games"] if str(g["id"]) == S.GAME)
        doc["games"] = []
        for i in range(30):
            g = copy.deepcopy(template)
            g["id"] = 2026029000 + i
            doc["games"].append(g)
        seen = []

        def fetch(url):
            seen.append(url)
            if url == nhl.SCORE_URL:
                return doc
            return S.box() if url.endswith("/boxscore") else S.pbp()
        report = nhl.fetch_and_store(S.NOW, fetch, max_requests=9)
        self.assertEqual(len(seen), 9)                                           # 1 score read + 4 games' box and play-by-play, then it stops
        self.assertEqual(len(report["detail_ok"]), 4)
        first_round = set(report["detail_ok"])
        seen.clear()
        report = nhl.fetch_and_store(S.at(10), fetch, max_requests=9)
        self.assertEqual(len(seen), 9)
        self.assertTrue(first_round.isdisjoint(report["detail_ok"]))            # the four never read go before the four read ten seconds ago

    def test_a_failed_score_read_changes_nothing_and_says_so(self):
        report = nhl.fetch_and_store(S.NOW, lambda url: (_ for _ in ()).throw(OSError("down")))
        self.assertEqual(report["games"], 0)
        self.assertIn("score", report["error"])
        self.assertEqual(store.fresh_games("NHL", S.NOW), [])

    def test_a_live_game_that_drops_off_the_days_list_is_asked_for_directly(self):
        nhl.fetch_and_store(S.NOW, self.fetch)
        trimmed = S.load("nhl_score_now.json")
        trimmed["games"] = [g for g in trimmed["games"] if str(g["id"]) != S.GAME]       # the list rolled to tomorrow
        calls = []

        def fetch(url):
            calls.append(url)
            return trimmed if url == nhl.SCORE_URL else S.fixture_fetch(url)
        nhl.fetch_and_store(S.at(70), fetch)
        self.assertTrue(any(u.endswith(f"{S.GAME}/boxscore") for u in calls))
        self.assertEqual(store.get("NHL", S.GAME, S.at(70))["as_of"], "2026-10-30T02:41:10Z")    # its base was refreshed from the boxscore

    def test_activity_decides_how_soon_the_next_score_read_is(self):
        self.assertTrue(nhl.fetch_and_store(S.NOW, self.fetch)["active"])
        quiet = S.load("nhl_score_now.json")
        quiet["games"] = [g for g in quiet["games"] if g["gameState"] in ("OFF", "FINAL")]
        report = nhl.fetch_and_store(S.at(600), lambda url: quiet)
        self.assertFalse(report["active"])


class TheSnapshotRow(unittest.TestCase):
    def test_the_row_is_compact_and_leaves_out_skaters_with_nothing_to_report(self):
        base = base_of(S.load("nhl_score_now.json"), S.GAME)
        base.update(nhl.derive_detail(S.box(), S.pbp()))
        base["as_of"] = "2026-10-30T02:40:00Z"
        row = nhl.log_row(base)
        self.assertEqual((row["a"], row["h"]), (["VAN", 1, 12], ["SJS", 0, 8]))
        self.assertEqual(row["gk"]["h"], [8482137, 11, 12])
        self.assertTrue(all(len(s) == 4 for s in row["sk"]["a"]))
        self.assertLess(len(row["sk"]["a"]), 18)                                 # only skaters with a point or a shot
        self.assertIn([8482055, 1, 0, 4], row["sk"]["a"])

    def test_the_clock_does_not_change_the_signature_but_a_shot_does(self):
        base = base_of(S.load("nhl_score_now.json"), S.GAME)
        base.update(nhl.derive_detail(S.box(), S.pbp()))
        base["as_of"] = "t"
        first = nhl.log_row(base)
        later = dict(base, seconds_remaining=900, clock="15:00", as_of="t2")
        self.assertEqual(nhl.signature(first), nhl.signature(nhl.log_row(later)))
        shot = dict(base, away=dict(base["away"], sog=13))
        self.assertNotEqual(nhl.signature(first), nhl.signature(nhl.log_row(shot)))


if __name__ == "__main__":
    unittest.main()
