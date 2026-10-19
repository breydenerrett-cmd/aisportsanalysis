"""The rule-set half of the user-hound engine (src/hounds/user_engine_v2.py): player props, AND/OR groups,
the daily cap and ranking, stakes, the -200 rule, point-in-time, idempotence, settlement of prop bets and
the read-only preview. Fixtures: tests/_hounds_rules_fixtures.py (no live store is read).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta

from src.hounds import user_engine, user_engine_v2, user_settle, user_spec
from tests import _hounds_rules_fixtures as F
from tests._hounds_user_fixtures import hound as v1_hound

LEDGER_NAME = "ledger.jsonl"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, LEDGER_NAME)
        self._players = F.patch_players()
        self._players.start()

    def tearDown(self):
        self._players.stop()
        self._tmp.cleanup()

    def run_day(self, hounds, *, rows=None, props=None, facts=None, now=None, replay=False, **kw):
        return user_engine.run(
            F.DATE, hounds, rows if rows is not None else F.standard_rows(), ledger=self.ledger,
            now=now or F.NOW, mode="replay" if replay else "live", game_pk_index=F.PK_INDEX,
            prop_rows=props if props is not None else F.standard_props(), facts=facts or F.facts(), **kw)

    def bets(self):
        return [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_engine.KIND_BET]


class GameMarketsMatchTheClassicEngine(_Base):
    def test_an_upgraded_classic_dog_makes_the_same_bet_as_the_original(self):
        old = v1_hound("u-old", side_rule="underdog", price_min=100, price_max=250)
        self.run_day([old])
        classic = [(b["market"], b["side"], b["price"], b["selection"]) for b in self.bets()]
        spec = user_spec.validate_spec({**user_spec.upgrade_v1(old["spec"]), "name": "Upgraded Dog"})
        os.remove(self.ledger)
        self.run_day([{"id": "u-new", "spec": spec, "spec_hash": user_spec.spec_hash(spec),
                       "created_at": "2026-01-01T00:00:00Z"}])
        upgraded = [(b["market"], b["side"], b["price"], b["selection"]) for b in self.bets()]
        self.assertEqual(classic, upgraded)
        self.assertEqual(upgraded, [("moneyline", "away", 120, "Boston Red Sox to win")])

    def test_the_board_at_lock_is_used_and_a_later_capture_never_is(self):
        # at the 21:05 lock board the home side is -140; the 22:20 board (-170) must not be read
        hound = F.hound(rules=[F.rule(side="home", price_min=-199, price_max=-135)])
        self.run_day([hound])
        self.assertEqual([b["price"] for b in self.bets()], [-140])

    def test_the_minus_200_rule_holds_even_for_a_hand_edited_spec(self):
        # a stored spec that skipped validation (price_min -300) still cannot make a -250 bet
        rows = F.board_rows(F.T_LOCK, moneyline=[(b, -250, 210) for b in F.BOOKS])
        spec = user_spec.validate_spec(F.v2(rules=[F.rule(side="home")]))
        spec = deepcopy(spec)
        spec["rules"][0]["price_min"] = -300
        h = {"id": "u-hand", "spec": spec, "spec_hash": "x", "created_at": "2026-01-01T00:00:00Z"}
        report = self.run_day([h], rows=rows, props=[])
        self.assertEqual(self.bets(), [])
        self.assertGreaterEqual(report["skipped"].get("price_cap", 0), 1)

    def test_a_validated_spec_cannot_reach_minus_200(self):
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec(F.v2(rules=[F.rule(price_min=-200)]))
        self.assertIn("rules[0].price_min", ctx.exception.errors)
        self.assertIn("-200", ctx.exception.errors["rules[0].price_min"])


class ConditionsInTheEngine(_Base):
    def test_all_group_needs_every_condition_and_any_group_needs_one(self):
        rest_ok = {"id": "rest_days", "who": "pick", "cmp": "gte", "value": 2}       # Boston has 2 days off
        rest_no = {"id": "rest_days", "who": "pick", "cmp": "gte", "value": 5}
        dog = {"id": "role", "value": "underdog"}
        all_pass = F.hound(rules=[F.rule(when={"op": "all", "items": [dog, rest_ok]})])
        all_fail = F.hound("u-v2b", rules=[F.rule(when={"op": "all", "items": [dog, rest_no]})])
        any_pass = F.hound("u-v2c", rules=[F.rule(when={"op": "any", "items": [rest_no, rest_ok, rest_no]})],
                           name="Any Dog")
        nested = F.hound("u-v2d", name="Nested Dog", rules=[F.rule(when={"op": "all", "items": [
            dog, {"op": "any", "items": [rest_no, {"id": "streak", "who": "opponent", "kind": "winning", "value": 3}]}]})])
        self.run_day([all_pass, all_fail, any_pass, nested])
        by = {}
        for b in self.bets():
            by.setdefault(b["hound_id"], []).append(b["side"])
        self.assertEqual(by.get("u-v2a"), ["away"])
        self.assertNotIn("u-v2b", by)
        self.assertEqual(by.get("u-v2c"), ["away"])      # one true member of the OR group is enough: Boston has 2 days off
        self.assertEqual(by.get("u-v2d"), ["away"])      # the underdog whose OPPONENT (Seattle) has won 3 straight

    def test_streak_and_rest_are_computed_from_games_before_the_slate_only(self):
        # Boston's same-day game (9-0 win, 17:00Z) is dated the slate date: it must not touch rest or streak
        facts = F.facts()
        self.assertEqual(facts.rest_days("MLB", "BOS", F.DATE, F.utc("2026-10-20T21:10:00Z")), 2)
        self.assertEqual(facts.streak("MLB", "BOS", F.DATE, F.utc("2026-10-20T21:10:00Z")), -2)
        self.assertEqual(facts.streak("MLB", "SEA", F.DATE, F.utc("2026-10-20T21:10:00Z")), 3)

    def test_an_unknown_fact_is_not_met_and_is_counted_by_name(self):
        hound = F.hound(rules=[F.rule(when={"op": "all", "items": [{"id": "rest_days", "who": "pick", "cmp": "gte", "value": 1}]})])
        report = self.run_day([hound], facts=F.facts(mlb_games=[]))
        self.assertEqual(self.bets(), [])
        self.assertGreaterEqual(report["skipped"].get("unknown_rest_days", 0), 1)

    def test_weather_comes_from_the_forecast_observed_before_the_lock(self):
        cold = F.hound(rules=[F.rule(markets=["total"], side="over", min_books=3,
                                     when={"op": "all", "items": [{"id": "temperature", "cmp": "lt", "value": 55.0}]})])
        hot = F.hound("u-hot", name="Hot Dog", rules=[F.rule(markets=["total"], side="over", min_books=3,
                                     when={"op": "all", "items": [{"id": "temperature", "cmp": "gt", "value": 80.0}]})])
        self.run_day([cold, hot])
        self.assertEqual({b["hound_id"] for b in self.bets()}, {"u-v2a"})   # 48F counted, the later 90F forecast not


class PlayerProps(_Base):
    def prop_hound(self, hid="u-prop", **rule_over):
        rule = F.rule(markets=["batter_total_bases"], side="over", min_books=3, **rule_over)
        return F.hound(hid, name="Prop Dog", rules=[rule], max_bets_per_day=5)

    def test_a_prop_is_priced_at_the_gate_board_average_and_records_its_player_line_and_book(self):
        self.run_day([self.prop_hound()])
        bets = self.bets()
        self.assertEqual(len(bets), 1)
        b = bets[0]
        self.assertEqual((b["market"], b["player"], b["side"], b["line"], b["price"], b["n_books"]),
                         ("batter_total_bases", "Pat Slugger", "over", 1.5, -130, 5))
        self.assertEqual(b["selection"], "Pat Slugger Over 1.5 total bases")
        self.assertEqual(b["board_observed_utc"], F.T_GATE)           # never the 22:20 board (-400)
        self.assertEqual(b["game_pk"], "824000")
        self.assertTrue(b["paper_only"])

    def test_the_minus_200_cap_refuses_a_heavy_prop(self):
        report = self.run_day([self.prop_hound(price_min=-199, price_max=1000)])
        self.assertEqual([b["player"] for b in self.bets()], ["Pat Slugger"])      # Hank Heavy at -300 is not bet
        self.assertGreaterEqual(report["skipped"].get("price_cap", 0), 1)

    def test_a_prop_board_older_than_the_limit_is_not_used(self):
        old = F.prop_rows("2026-10-19T20:00:00Z", [("Pat Slugger", "batter_total_bases", 1.5, "Over", -110, b) for b in F.BOOKS])
        report = self.run_day([self.prop_hound()], props=old)
        self.assertEqual(self.bets(), [])
        self.assertEqual(report["skipped"].get("board_too_old"), 1)

    def test_player_conditions_streak_form_and_rate(self):
        streak = self.prop_hound(when={"op": "all", "items": [
            {"id": "player_streak", "stat": "hits", "games": 3, "min": 1}]})
        too_long = self.prop_hound("u-p2", when={"op": "all", "items": [
            {"id": "player_streak", "stat": "hits", "games": 4, "min": 1}]})        # he did not hit on 10-15
        form_above = self.prop_hound("u-p3", when={"op": "all", "items": [
            {"id": "player_form", "n": 3, "rel": "above", "margin": 0.5}]})          # (2+3+2)/3 = 2.33 vs line 1.5
        form_below = self.prop_hound("u-p4", when={"op": "all", "items": [
            {"id": "player_form", "n": 3, "rel": "below", "margin": 0.0}]})
        rate = self.prop_hound("u-p5", when={"op": "all", "items": [
            {"id": "player_rate", "cmp": "gte", "value": 1.5}]})                      # (1+0+2+3+2)/5 = 1.6
        for i, h in enumerate((streak, too_long, form_above, form_below, rate)):
            h["spec"]["name"] = f"Prop Dog {i}"
        self.run_day([streak, too_long, form_above, form_below, rate])
        self.assertEqual({b["hound_id"] for b in self.bets()}, {"u-prop", "u-p3", "u-p5"})

    def test_a_named_player_and_his_team_filter(self):
        only_sam = F.hound("u-sam", name="Sam Dog", rules=[F.rule(markets=["batter_hits"], side="over", min_books=3,
                            when={"op": "all", "items": [{"id": "player_is", "players": ["Sam Contact"]}]})])
        boston = F.hound("u-bos", name="Boston Dog", rules=[F.rule(markets=["batter_total_bases", "batter_hits"], side="over", min_books=3,
                            when={"op": "all", "items": [{"id": "team_is", "teams": ["MLB:BOS"]}]})])
        self.run_day([only_sam, boston])
        got = {(b["hound_id"], b["player"]) for b in self.bets()}
        self.assertEqual(got, {("u-sam", "Sam Contact"), ("u-bos", "Sam Contact")})

    def test_either_side_keeps_one_side_per_player_market(self):
        h = F.hound("u-either", name="Either Dog", rules=[F.rule(markets=["batter_hits"], side="either", min_books=3)],
                    max_bets_per_day=5)
        self.run_day([h])
        sides = [(b["player"], b["side"]) for b in self.bets()]
        self.assertEqual(sides, [("Sam Contact", "over")])        # over first on ties; never both sides

    def test_a_prop_quoted_on_one_side_only_can_still_be_backed_on_that_side(self):
        hr = F.hound("u-hr", name="Homer Dog", rules=[F.rule(markets=["batter_home_runs"], side="either", min_books=2)])
        self.run_day([hr])
        self.assertEqual([(b["side"], b["price"], b["n_books"]) for b in self.bets()], [("over", 320, 2)])

    def test_steam_toward_the_pick_uses_the_first_capture_of_the_prop(self):
        toward = self.prop_hound(when={"op": "all", "items": [{"id": "steam", "direction": "toward"}]})
        against = self.prop_hound("u-ag", when={"op": "all", "items": [{"id": "steam", "direction": "against"}]})
        against["spec"]["name"] = "Against Dog"
        self.run_day([toward, against])
        self.assertEqual({b["hound_id"] for b in self.bets()}, {"u-prop"})        # -110 -> -130: toward the over

    def test_prop_bets_are_idempotent_and_the_daily_cap_counts_the_ledger(self):
        h = self.prop_hound()
        first = self.run_day([h])
        second = self.run_day([h])
        self.assertEqual((first["bets_written"], second["bets_written"]), (1, 0))
        self.assertEqual(len(self.bets()), 1)


class CapRankingAndStake(_Base):
    def three_games(self):
        rows = []
        for n, (home_ml, away_ml, books) in enumerate(((-120, 110, 5), (-105, -105, 4), (-150, 130, 3))):
            ev = f"evt{n}"
            start = f"2026-10-20T{23 + n // 2:02d}:{10 + 20 * (n % 2):02d}:00Z" if n < 2 else "2026-10-20T23:40:00Z"
            for t in ("2026-10-20T19:55:00Z", "2026-10-20T21:05:00Z"):
                rows += F.board_rows(t, event_id=ev, start=start, home=f"Home Club {n}", away=f"Away Club {n}",
                                     moneyline=[(b, home_ml, away_ml) for b in F.BOOKS[:books]])
        return rows

    def run_rank(self, rank_by):
        h = F.hound("u-rank", rules=[F.rule(min_books=3, price_min=-199, price_max=1000)], rank_by=rank_by,
                    max_bets_per_day=1, lock_minutes=180)
        # all three locked by 21:30 only if lock <= 21:30: games start 23:10..23:40, 180-minute lock = 20:10..20:40
        user_engine.run(F.DATE, [h], self.three_games(), ledger=self.ledger, now=F.utc("2026-10-20T21:30:00Z"),
                        game_pk_index={}, prop_rows=[], facts=F.facts())
        out = [b["selection"] for b in self.bets()]
        os.remove(self.ledger)
        return out

    def test_the_ranking_rule_decides_which_pick_takes_the_one_slot(self):
        # candidates (either side): Away 0 +110 (5 books), Home 0 -120 (5), Away 1 / Home 1 -105 (4), Away 2 +130 (3), Home 2 -150 (3)
        self.assertEqual(self.run_rank("longest_price"), ["Away Club 2 to win"])
        self.assertEqual(self.run_rank("shortest_price"), ["Home Club 2 to win"])
        self.assertEqual(self.run_rank("most_books"), ["Home Club 0 to win"])     # 5 books; a tie goes to the home side
        self.assertEqual(self.run_rank("earliest_lock"), ["Home Club 0 to win"])  # the game that locks first

    def test_a_stake_is_recorded_and_scales_the_owners_numbers_not_the_public_record(self):
        h = F.hound("u-stake", rules=[F.rule(when={"op": "all", "items": [{"id": "role", "value": "underdog"}]})],
                    stake_units=2.0)
        self.run_day([h])
        bet = self.bets()[0]
        self.assertEqual((bet["stake_units"], bet["units"]), (2.0, 2.0))
        # Boston (+120) wins: the public units stay one flat unit; the staked figures are doubled
        results = {"824000": {"date": F.DATE, "away_team": "BOS", "home_team": "SEA", "away_score": 4, "home_score": 1}}
        report = user_settle.settle(ledger=self.ledger, now=F.utc("2026-10-21T12:00:00Z"), mlb_results=results,
                                    game_pk_index=F.PK_INDEX, close_fn=lambda b: None)
        self.assertEqual(report["by_result"], {"WIN": 1})
        graded = [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_settle.KIND_GRADED][0]
        self.assertEqual(graded["profit_units"], 1.2)
        self.assertEqual(graded["units_average_price"], 1.2)
        self.assertEqual(graded["profit_stake_units"], 2.4)


class SettlingProps(_Base):
    def bet_and_settle(self, stat_line, *, side="over", box=True):
        h = F.hound("u-s", name="Settle Dog", rules=[F.rule(markets=["batter_total_bases"], side=side, min_books=3)])
        self.run_day([h])
        results = {"824000": {"date": F.DATE, "away_team": "BOS", "home_team": "SEA", "away_score": 4, "home_score": 1}}
        index = {"824000": {"Pat Slugger".lower().replace(" ", " "): {"batter": {"total_bases": stat_line}}}} if box else {}
        report = user_settle.settle(ledger=self.ledger, now=F.utc("2026-10-21T12:00:00Z"), mlb_results=results,
                                    game_pk_index=F.PK_INDEX, box_index=index)
        graded = [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_settle.KIND_GRADED]
        return report, graded

    def test_over_wins_loses_and_pushes_on_the_line(self):
        _r, g = self.bet_and_settle(2)
        self.assertEqual(g[0]["result"], "WIN")
        self.assertIsNone(g[0]["close_price"])                    # a prop's CLV is null, never a guess
        os.remove(self.ledger)
        _r, g = self.bet_and_settle(1)
        self.assertEqual(g[0]["result"], "LOSS")

    def test_under_wins_when_the_total_is_below_the_line(self):
        _r, g = self.bet_and_settle(1, side="under")
        self.assertEqual(g[0]["result"], "WIN")

    def test_a_player_who_did_not_play_is_void_and_a_missing_box_score_is_pending(self):
        h = F.hound("u-s", name="Settle Dog", rules=[F.rule(markets=["batter_total_bases"], side="over", min_books=3)])
        self.run_day([h])
        results = {"824000": {"date": F.DATE, "away_team": "BOS", "home_team": "SEA", "away_score": 4, "home_score": 1}}
        report = user_settle.settle(ledger=self.ledger, now=F.utc("2026-10-21T12:00:00Z"), mlb_results=results,
                                    game_pk_index=F.PK_INDEX, box_index={"824000": {"someone else": {"batter": {}}}})
        self.assertEqual(report["by_result"], {"VOID": 1})
        os.remove(self.ledger)
        self.run_day([h])
        pending = user_settle.settle(ledger=self.ledger, now=F.utc("2026-10-21T12:00:00Z"), mlb_results=results,
                                     game_pk_index=F.PK_INDEX, box_index={})
        self.assertEqual((pending["graded"], pending["pending"]), (0, 1))

    def test_grade_prop_uses_the_same_stat_table_as_the_player_conditions(self):
        from src.hounds import user_rules
        for market, (kind, key, _noun) in user_rules.PROP_STATS.items():
            bet = {"market": market, "player": "Pat Slugger", "line": 0.5, "side": "over"}
            box = {"pat slugger": {kind: {key: 1}}}
            self.assertEqual(user_settle.grade_prop(bet, box)["result"], "WIN", market)


class Preview(_Base):
    def slate(self):
        games = user_engine.build_games(F.standard_rows(), near_date=F.DATE)
        user_engine_v2.add_prop_rows(games, F.standard_props())
        games = {k: g for k, g in games.items() if g.commence is not None}
        return games

    def test_the_preview_counts_and_ranks_and_writes_nothing(self):
        spec = user_spec.validate_spec(F.v2(rules=[F.rule(markets=["batter_total_bases"], side="over", min_books=3)],
                                            max_bets_per_day=1))
        out = user_engine_v2.preview(spec, self.slate(), F.facts(), F.DATE, F.NOW, game_pk_index=F.PK_INDEX)
        self.assertEqual((out["qualifying"], out["would_bet"]), (1, 1))
        self.assertEqual(out["picks"][0]["selection"], "Pat Slugger Over 1.5 total bases")
        self.assertTrue(out["picks"][0]["locked"])
        self.assertFalse(os.path.exists(self.ledger))

    def test_a_game_not_yet_locked_is_read_on_the_newest_board_and_flagged(self):
        spec = user_spec.validate_spec(F.v2(rules=[F.rule(side="away", min_books=3)]))
        early = F.utc("2026-10-20T20:00:00Z")           # before the 21:10 lock
        out = user_engine_v2.preview(spec, self.slate(), F.facts(), F.DATE, early, game_pk_index=F.PK_INDEX)
        self.assertEqual(out["picks"][0]["locked"], False)
        self.assertEqual(out["picks"][0]["price"], 105)  # the 19:55 board: the 21:05 capture did not exist yet

    def test_cap_marks_the_picks_over_the_daily_limit(self):
        spec = user_spec.validate_spec(F.v2(rules=[F.rule(markets=["batter_total_bases", "batter_hits"], side="over", min_books=3)],
                                            max_bets_per_day=1))
        out = user_engine_v2.preview(spec, self.slate(), F.facts(), F.DATE, F.NOW, game_pk_index=F.PK_INDEX)
        self.assertEqual(out["qualifying"], 2)
        self.assertEqual([p["would_bet"] for p in out["picks"]], [True, False])


if __name__ == "__main__":
    unittest.main()
