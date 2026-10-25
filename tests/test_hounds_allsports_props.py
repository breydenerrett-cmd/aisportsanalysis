"""NBA and NHL player props for member hounds, end to end: the menu's sport rule (a prop is only priced for its own
sport), the engine's candidates from the captured all-sports prop store at the lock, and settlement from the ESPN box
score through the data service. Fixtures: tests/_hounds_rules_fixtures.py for the hound and the facts; the NBA box is
the repo's saved real ESPN summary (tests/fixtures/datasvc_espn/nba_summary.json). No live store or network is read.

The prop row shape is src/pipeline/allsports_props.py's `project` (one row per market, book, player, side, line).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.appstate import card_ledger
from src.datasvc.espn import parse
from src.hounds import user_engine, user_rules, user_settle, user_spec
from src.pipeline import allsports_props_grade as grade
from tests import _hounds_rules_fixtures as F

FIX = Path(__file__).resolve().parent / "fixtures" / "allsports_props"   # saved real ESPN summaries (NBA, NHL)
NBA_EVENT = "nba-evt-1"
NBA_START = "2026-10-20T23:10:00Z"
NBA_HOME, NBA_AWAY = "Memphis Grizzlies", "Orlando Magic"
BOOKS = ("fanduel", "draftkings", "betmgm", "caesars")
T_GATE, T_LATE = "2026-10-20T21:05:00Z", "2026-10-20T22:20:00Z"     # lock is 21:10Z (120 minutes before the start)
NOW = F.utc("2026-10-20T21:30:00Z")


def prop_row(player, market, line, side, price, book, observed, *, sport="NBA", league="basketball_nba",
             event=NBA_EVENT, start=NBA_START, home=NBA_HOME, away=NBA_AWAY):
    """One row in the all-sports prop store's shape (`allsports_props.project`)."""
    return {"event_id": event, "game_date": F.DATE, "commence_time": start, "home_team": home, "away_team": away,
            "market": market, "selection": f"{player}:{side}", "player": player, "side": side, "line": str(line),
            "price": price, "book": book, "book_last_update": observed, "observed_utc": observed,
            "capture_phase": "t2h", "sport": sport, "league": league}


def espn_box(game_id="4000001", *, completed=True):
    """The data service's box for one game, built from the saved real ESPN NBA summary through the real parser."""
    summary = json.loads((FIX / "espn_nba_summary_sample.json").read_text(encoding="utf-8"))
    game = {"league": "nba", "game_id": game_id, "date_utc": NBA_START, "season": 2026}
    rows = parse.player_games(summary, game, "2026-10-21T12:00:00Z")
    return {"game": {"league": "nba", "game_id": game_id, "completed": completed,
                     "state": "post" if completed else "in",
                     "status": "STATUS_FINAL" if completed else "STATUS_IN_PROGRESS",
                     "date_utc": NBA_START, "home_name": NBA_HOME, "away_name": NBA_AWAY},
            "team_games": [], "player_games": rows}


class FakeLeague:
    """The `league(code)` read of the data service: the schedule for a day, and one game's box."""

    def __init__(self, games=(), boxes=None):
        self.games, self.boxes = list(games), dict(boxes or {})

    def schedule(self, date=None, **_kw):
        rows = [g for g in self.games if g["scoreboard_date"] == date]
        return {"available": True, "sport": "nba", "kind": "schedule", "data": rows}

    def game(self, game_id, **_kw):
        if str(game_id) in self.boxes:
            return self.boxes[str(game_id)]
        return {"available": False, "missing": [{"item": "game", "reason": "no box"}]}


class FakeClient:
    def __init__(self, league):
        self._league = league

    def league(self, code):
        assert code == "nba", code
        return self._league


def schedule_row(game_id="4000001", home=NBA_HOME, away=NBA_AWAY, date_utc=NBA_START, day=F.DATE):
    return {"game_id": game_id, "home_name": home, "away_name": away, "date_utc": date_utc, "scoreboard_date": day,
            "state": "post", "completed": True}


def nba_bet(market, player, line, side="over", **over):
    bet = {"sport": "NBA", "slate_date": F.DATE, "home_team": NBA_HOME, "away_team": NBA_AWAY,
           "commence_time": NBA_START, "market": market, "player": player, "side": side, "line": line}
    bet.update(over)
    return bet


class MenuAndValidation(unittest.TestCase):
    def errors(self, rule_over):
        try:
            user_spec.validate_spec(F.v2(rules=[F.rule(**rule_over)]))
        except user_spec.SpecError as exc:
            return exc.errors
        return {}

    def test_the_menu_names_each_props_sports(self):
        self.assertEqual(user_rules.prop_sports("player_points"), ("NBA", "NHL"))
        self.assertEqual(user_rules.prop_sports("player_rebounds"), ("NBA",))
        self.assertEqual(user_rules.prop_sports("player_shots_on_goal"), ("NHL",))
        self.assertEqual(user_rules.prop_sports("batter_hits"), ("MLB",))
        self.assertEqual(user_rules.prop_sports("moneyline"), ())

    def test_the_builder_menu_offers_each_prop_only_for_its_sports(self):
        by_value = {m["value"]: m for m in user_spec.builder_menu()["markets"]}
        self.assertEqual(by_value["player_points"]["sports"], ["NBA", "NHL"])
        self.assertEqual(by_value["player_threes"]["sports"], ["NBA"])
        self.assertEqual(by_value["player_total_saves"]["sports"], ["NHL"])
        self.assertEqual(by_value["batter_hits"]["sports"], ["MLB"])
        self.assertEqual(by_value["moneyline"]["sports"], list(user_spec.SPORTS))

    def test_nhl_and_nba_props_validate_for_their_own_sport(self):
        self.assertEqual(self.errors({"sports": ["NHL"], "markets": ["player_shots_on_goal"], "side": "over"}), {})
        self.assertEqual(self.errors({"sports": ["NHL"], "markets": ["player_total_saves"], "side": "under"}), {})
        self.assertEqual(self.errors({"sports": ["NBA"], "markets": ["player_points_rebounds_assists"],
                                      "side": "over"}), {})
        self.assertEqual(self.errors({"sports": ["NBA", "NHL"], "markets": ["player_points"], "side": "over"}), {})

    def test_an_nhl_rule_with_an_mlb_prop_is_refused(self):
        errors = self.errors({"sports": ["NHL"], "markets": ["batter_hits"], "side": "over"})
        self.assertIn("rules[0].sports", errors)
        self.assertIn("Batter hits works for MLB only", errors["rules[0].sports"])

    def test_a_stat_the_other_sport_does_not_price_is_refused(self):
        self.assertIn("rules[0].sports", self.errors({"sports": ["NBA"], "markets": ["player_shots_on_goal"],
                                                      "side": "over"}))
        self.assertIn("rules[0].sports", self.errors({"sports": ["NBA", "NHL"], "markets": ["player_rebounds"],
                                                      "side": "over"}))

    def test_a_market_key_the_store_does_not_capture_is_not_on_the_menu(self):
        self.assertIn("rules[0].markets", self.errors({"sports": ["NHL"], "markets": ["player_goals"], "side": "over"}))
        self.assertNotIn("player_goals", user_rules.ALL_MARKETS)
        self.assertNotIn("goalie_saves", user_rules.ALL_MARKETS)


class EngineCandidates(unittest.TestCase):
    def setUp(self):
        self._players = F.patch_players()
        self._players.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, "ledger.jsonl")

    def tearDown(self):
        self._players.stop()
        self._tmp.cleanup()

    def run_with(self, sports, rules, rows):
        hound = F.hound("u-" + "-".join(sports).lower(), name="Court Dog", rules=rules, max_bets_per_day=5)
        user_engine.run(F.DATE, [hound], [], ledger=self.ledger, now=NOW, mode="replay", game_pk_index={},
                        prop_rows=rows, facts=F.facts())
        return [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_engine.KIND_BET]

    def test_an_nba_prop_is_a_candidate_at_the_lock_board_only(self):
        rows = [prop_row("Jaren Jackson Jr.", "player_rebounds", 6.5, "Over", -115, b, T_GATE) for b in BOOKS]
        rows += [prop_row("Jaren Jackson Jr.", "player_rebounds", 6.5, "Over", -400, b, T_LATE) for b in BOOKS]
        rule = F.rule(sports=["NBA"], markets=["player_rebounds"], side="over", min_books=3)
        bets = self.run_with(["NBA"], [rule], rows)
        self.assertEqual(len(bets), 1)
        bet = bets[0]
        self.assertEqual((bet["sport"], bet["market"], bet["player"], bet["side"]),
                         ("NBA", "player_rebounds", "Jaren Jackson Jr.", "over"))
        self.assertEqual(bet["line"], 6.5)
        self.assertEqual(bet["price"], -115)                    # the 21:05 board, never the 22:20 one
        self.assertEqual(bet["board_observed_utc"], T_GATE)
        self.assertEqual(bet["league"], "basketball_nba")

    def test_the_minus_200_cap_refuses_a_heavy_nba_prop(self):
        rows = [prop_row("Paolo Banchero", "player_points", 25.5, "Over", -300, b, T_GATE) for b in BOOKS]
        rule = F.rule(sports=["NBA"], markets=["player_points"], side="over", min_books=3)
        self.assertEqual(self.run_with(["NBA"], [rule], rows), [])

    def test_an_nhl_rule_reads_nhl_rows_and_not_nba_rows(self):
        nhl = [prop_row("Connor McDavid", "player_shots_on_goal", 3.5, "Over", 110, b, T_GATE, sport="NHL",
                        league="icehockey_nhl") for b in BOOKS]
        nba = [prop_row("Paolo Banchero", "player_points", 25.5, "Over", -110, b, T_GATE) for b in BOOKS]
        rule = F.rule(sports=["NHL"], markets=["player_shots_on_goal"], side="over", min_books=3)
        bets = self.run_with(["NHL"], [rule], nhl + nba)
        self.assertEqual([(b["sport"], b["market"], b["line"]) for b in bets],
                         [("NHL", "player_shots_on_goal", 3.5)])


class GradingAndSettlement(unittest.TestCase):
    def test_the_bet_finds_its_espn_game_by_teams_and_start_time(self):
        client = FakeClient(FakeLeague([schedule_row()]))
        self.assertEqual(grade.find_espn_game(nba_bet("player_points", "Jaren Jackson Jr.", 28.5), client),
                         ("4000001", None))

    def test_accents_and_case_do_not_stop_a_team_match(self):
        league = FakeLeague([schedule_row(home="Memphis Grizzlies", away="Orlando Magic")])
        bet = nba_bet("player_points", "Jaren Jackson Jr.", 28.5, home="MEMPHIS GRIZZLIES", away="Orlando Magic")
        self.assertEqual(grade.find_espn_game(bet, FakeClient(league))[0], "4000001")

    def test_two_games_that_fit_are_ambiguous_and_not_graded(self):
        league = FakeLeague([schedule_row("4000001"), schedule_row("4000002")])
        game_id, why = grade.find_espn_game(nba_bet("player_points", "Jaren Jackson Jr.", 28.5), FakeClient(league))
        self.assertIsNone(game_id)
        self.assertIn("ambiguous", why)

    def test_no_game_on_the_schedule_is_pending_not_void(self):
        verdict = grade.settle_prop(nba_bet("player_points", "Jaren Jackson Jr.", 28.5), FakeClient(FakeLeague([])))
        self.assertEqual(verdict["status"], grade.UNRESOLVED)

    def test_a_points_prop_is_graded_from_the_espn_box(self):
        league = FakeLeague([schedule_row()], {"4000001": {"available": True, "data": espn_box()}})
        verdict = grade.settle_prop(nba_bet("player_points", "Jaren Jackson Jr.", 28.5), FakeClient(league))
        self.assertEqual((verdict["status"], verdict["actual"]), (grade.WIN, 30.0))

    def test_a_stat_the_saved_box_does_not_carry_stays_pending(self):
        league = FakeLeague([schedule_row()], {"4000001": {"available": True, "data": espn_box()}})
        verdict = grade.settle_prop(nba_bet("player_rebounds", "Jaren Jackson Jr.", 6.5), FakeClient(league))
        self.assertEqual(verdict["status"], grade.UNRESOLVED)

    def test_a_game_still_in_progress_is_pending(self):
        league = FakeLeague([schedule_row()], {"4000001": {"available": True, "data": espn_box(completed=False)}})
        verdict = grade.settle_prop(nba_bet("player_points", "Jaren Jackson Jr.", 28.5), FakeClient(league))
        self.assertEqual(verdict["status"], grade.UNRESOLVED)

    def test_an_nhl_stat_the_saved_nhl_box_does_not_carry_is_unresolved_not_zero(self):
        # The saved NHL sample is a real ESPN summary with no goal, assist or shot keys: a shots prop on it is
        # pending, never a zero, and a skater who is in the box is found by name.
        summary = json.loads((FIX / "espn_nhl_summary_sample.json").read_text(encoding="utf-8"))
        game = {"league": "nhl", "game_id": "5000001", "date_utc": NBA_START, "season": 2026}
        rows = parse.player_games(summary, game, "2026-10-21T12:00:00Z")
        box = {"game": {"league": "nhl", "game_id": "5000001", "completed": True, "state": "post",
                        "status": "STATUS_FINAL"}, "team_games": [], "player_games": rows}
        bet = {"sport": "NHL", "market": "player_shots_on_goal", "player": "Josh Anderson", "side": "over", "line": 2.5}
        verdict = grade.grade_prop(bet, box)
        self.assertEqual(verdict["status"], grade.UNRESOLVED)
        self.assertIn("cannot answer", verdict["reason"])

    def test_a_player_who_did_not_play_is_void_on_a_constructed_dnp(self):
        # The saved sample has no DNP row, so the DNP is made here by marking a real row, and the test says so.
        box = espn_box()
        for row in box["player_games"]:
            if row["player_name"] == "Jock Landale":
                row["did_not_play"] = True
        league = FakeLeague([schedule_row()], {"4000001": {"available": True, "data": box}})
        verdict = grade.settle_prop(nba_bet("player_points", "Jock Landale", 10.5), FakeClient(league))
        self.assertEqual(verdict["status"], grade.VOID)

    def test_settlement_grades_an_nba_prop_bet_from_its_box_score(self):
        ledger = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")
        hound = F.hound("u-nba-settle", name="Court Dog", max_bets_per_day=5,
                        rules=[F.rule(sports=["NBA"], markets=["player_points"], side="over", min_books=3)])
        rows = [prop_row("Jaren Jackson Jr.", "player_points", 28.5, "Over", -110, b, T_GATE) for b in BOOKS]
        user_engine.run(F.DATE, [hound], [], ledger=ledger, now=NOW, mode="replay", game_pk_index={},
                        prop_rows=rows, facts=F.facts())
        league = FakeLeague([schedule_row()], {"4000001": {"available": True, "data": espn_box()}})
        report = user_settle.settle(ledger=ledger, now=F.utc("2026-10-21T12:00:00Z"), mlb_results={},
                                    game_pk_index={}, box_index={}, props_client=FakeClient(league))
        graded = [r for r in user_engine.read_ledger(ledger) if r.get("kind") == user_settle.KIND_GRADED]
        self.assertEqual([g["result"] for g in graded], [card_ledger.RESULT_WIN])
        self.assertEqual(report["pending"], 0)


if __name__ == "__main__":
    unittest.main()
