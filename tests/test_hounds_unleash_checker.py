"""Checker regressions for Unleash (2026-10-21): what the first build missed.

  * A game whose LOCK has passed but which has not started is placed (by Unleash, as by a late normal pass) on the board as
    it stood AT ITS LOCK, never on a later one; a game only a post-lock board would qualify is not bet at all.
  * The manual pick (one card, or "Add all as manual picks") works for a dog built from English rules (version 2). Until now
    ``manual.record`` called ``fire_user``, which reads fields only a classic spec has, so the button on every card of such a dog
    answered 500, and the Unleash panel hid that by leaving its list empty for them.
  * One side per game in the manual path: the second of a Suns moneyline / Suns +2.5 pair is skipped with the rule's reason.

Nothing reads a live store: boards, facts and ledgers are injected.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from src.hounds import user_engine, user_engine_v2
from src.hounds.interact import common, fire, manual, unleash
from tests import _hounds_rules_fixtures as RF
from tests._hounds_user_fixtures import BOOKS, board_rows, hound, utc
from tests.test_hounds_unleash import NOW, OWNER, INDEX, _Case, day_rows, game, manual_rows

DOG = {"op": "all", "items": [{"id": "role", "value": "underdog"}]}


class LockedButNotStarted(_Case):
    """lk: starts 19:30Z, lock 17:30Z, now 18:00Z. Lock-time board (17:20Z) +130; a post-lock board (17:50Z) says +180.
    lk2: lock-time board is pick'em; a post-lock board (17:50Z) says +150, which would qualify if it were used."""

    def rows(self):
        rows = day_rows()
        rows += game("lk", "2026-10-20T17:20:00Z", 130, -150, "2026-10-20T19:30:00Z", "Kansas City Royals", "Minnesota Twins")
        rows += game("lk", "2026-10-20T17:50:00Z", 180, -210, "2026-10-20T19:30:00Z", "Kansas City Royals", "Minnesota Twins")
        rows += game("lk2", "2026-10-20T17:20:00Z", -110, -110, "2026-10-20T19:40:00Z", "Houston Astros", "Oakland Athletics")
        rows += game("lk2", "2026-10-20T17:50:00Z", 150, -170, "2026-10-20T19:40:00Z", "Houston Astros", "Oakland Athletics")
        return rows

    def test_it_is_placed_on_the_board_at_its_lock_and_a_later_price_is_never_used(self):
        out = self.go(rows=self.rows())
        lk = next(p for p in out["picks"] if p["event_id"] == "lk")
        self.assertEqual(lk["price_average"], 130)                                   # not the +180 of 17:50Z
        row = next(r for r in self.bets() if r["event_id"] == "lk")
        self.assertEqual((row["price"], row["board_observed_utc"]), (130, "2026-10-20T17:20:00Z"))
        self.assertLessEqual(row["board_observed_utc"], row["lock_utc"])             # no board newer than the lock
        self.assertEqual(row["recorded_utc"], "2026-10-20T18:00:00Z")                # written late, priced at the lock

    def test_a_game_only_a_post_lock_board_would_qualify_is_not_bet_and_not_in_the_before_list(self):
        out = self.go(rows=self.rows())
        self.assertNotIn("lk2", {r["event_id"] for r in self.bets()})
        self.assertNotIn("lk2", {b["event_id"] for b in out["before"]})
        self.assertNotIn("lk2", {p["event_id"] for p in out["picks"]})

    def test_the_manual_offer_for_it_says_the_placing_time_has_passed_not_placed_when_it_locks(self):
        out = self.go(rows=self.rows())
        other = {o["event_id"]: o for o in out["other_picks"]}
        self.assertEqual(other["lk2"]["why_not_placed"], "past_lock")                # it IS past its lock
        self.assertNotIn("Placed when it locks", other["lk2"]["why_text"])


def _slate_for(rows, facts=None):
    def slate_for(date, with_props):
        return user_engine_v2.build_slate(date, ["MLB"], with_props=with_props, rows=rows, prop_rows=[],
                                          facts=facts or RF.facts(), game_pk_index=RF.PK_INDEX)
    return slate_for


EARLY = utc("2026-10-20T20:00:00Z")                      # the standard game's 120-minute lock is 21:10Z


def two_games():
    rows = RF.standard_rows()
    rows += board_rows("2026-10-20T19:55:00Z", event_id="evt0002", home="Cleveland Guardians", away="Toronto Blue Jays",
                       start="2026-10-20T23:40:00Z", moneyline=[(b, -160, 140) for b in BOOKS])
    return rows


class ManualPicksForEnglishRulesDogs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        self.manual_ledger = os.path.join(self._tmp.name, "manual.jsonl")
        players = RF.patch_players()
        players.start()
        self.addCleanup(players.stop)
        h = RF.hound("u-v2man", created_at="2026-10-20T06:00:00Z", max_bets_per_day=1,
                     rules=[RF.rule(side="away", price_min=100, price_max=250)])
        self.dog = common.Dog(id=h["id"], kind=common.KIND_USER, name=h["spec"]["name"], hound=h, owner_user_id=OWNER,
                              status="running", root_id=h["id"])

    def unleash(self, rows=None):
        return unleash.unleash(self.dog, OWNER, now=EARLY, rows=rows or two_games(), ledger=self.ledger,
                               game_pk_index=RF.PK_INDEX, facts=RF.facts(), prop_rows=[], mlb_results={},
                               nfl_results=lambda _d: {}, allsports_results={}, refresh_stats=lambda: None,
                               manual_ledger=self.manual_ledger)

    def batch(self, picks, rows=None):
        return manual.record_batch(self.dog, OWNER, picks, now=EARLY, ledger=self.manual_ledger, rule_ledger=self.ledger,
                                   slate_for=_slate_for(rows or two_games()))

    def test_the_other_picks_of_an_english_rules_dog_are_listed_not_empty(self):
        out = self.unleash()
        self.assertEqual([p["event_id"] for p in out["picks"]], [RF.EVENT])             # the day's limit of one
        self.assertEqual([(o["event_id"], o["can_record"], o["why_not_placed"]) for o in out["other_picks"]],
                         [("evt0002", True, "over_limit")])
        self.assertEqual(out["other_picks"][0]["price_average"], 140)

    def test_add_all_records_them_in_the_manual_ledger_only_and_a_second_tap_adds_nothing(self):
        out = self.unleash()
        picks = [{"event_id": o["event_id"], "market": o["market"]} for o in out["other_picks"]]
        rule_before = open(self.ledger, "rb").read()
        first = self.batch(picks)
        self.assertEqual((first["added"], first["skipped"], first["line"]), (1, 0, "Added 1"))
        rows = manual_rows(self.manual_ledger)
        self.assertEqual([(r["event_id"], r["manual"], r["provenance"], r["price"]) for r in rows],
                         [("evt0002", True, "manual", 140)])
        self.assertEqual((rows[0]["rule_index"], rows[0]["spec_version"]), (0, 2))       # the rule-set engine's own row
        self.assertEqual(open(self.ledger, "rb").read(), rule_before)                    # never the rule's record
        again = self.batch(picks)
        self.assertEqual((again["added"], again["skipped"]), (0, 1))
        self.assertEqual(again["reasons"][0]["reason"], "already recorded as a manual pick")
        self.assertEqual(len(manual_rows(self.manual_ledger)), 1)

    def test_the_card_button_path_manual_record_works_too(self):
        self.unleash()
        ticket = manual.record(self.dog, OWNER, "evt0002", "moneyline", now=EARLY, ledger=self.manual_ledger,
                               rule_ledger=self.ledger, slate_for=_slate_for(two_games()))
        self.assertEqual(ticket["price_average"], 140)
        with self.assertRaises(manual.ManualError) as ctx:                               # the rule's own bet is on the record
            manual.record(self.dog, OWNER, RF.EVENT, "moneyline", now=EARLY, ledger=self.manual_ledger,
                          rule_ledger=self.ledger, slate_for=_slate_for(two_games()))
        self.assertEqual(ctx.exception.code, "already_on_record")

    def test_a_started_game_is_never_added(self):
        self.unleash()
        late = utc("2026-10-20T23:50:00Z")                                              # evt0002 started at 23:40Z
        out = manual.record_batch(self.dog, OWNER, [{"event_id": "evt0002", "market": "moneyline"}], now=late,
                                  ledger=self.manual_ledger, rule_ledger=self.ledger, slate_for=_slate_for(two_games()))
        self.assertEqual((out["added"], out["reasons"][0]["reason"]), (0, "game already started"))
        self.assertEqual(manual_rows(self.manual_ledger), [])

    def test_a_player_prop_pick_is_one_ticket_per_player(self):
        self.assertNotEqual(manual.manual_bet_id("d", "e", "batter_hits", "Pat Slugger"),
                            manual.manual_bet_id("d", "e", "batter_hits", "Sam Contact"))
        self.assertEqual(manual.manual_bet_id("d", "e", "moneyline"), manual.manual_bet_id("d", "e", "moneyline", None))
        self.assertEqual(manual.manual_bet_id("d", "e", "batter_hits", "Pat Slugger"),
                         manual.manual_bet_id("d", "e", "batter_hits", "pat  slugger"))


def pair_rows():
    return board_rows("2026-10-20T19:30:00Z", event_id="pair", home="Los Angeles Dodgers", away="San Diego Padres",
                      start="2026-10-20T23:40:00Z", moneyline=[(b, -140, 120) for b in BOOKS],
                      spread=(-1.5, [(b, 160, -190) for b in BOOKS]))


class OneSidePerGameInTheBulkAdd(unittest.TestCase):
    """San Diego moneyline +120 and San Diego +1.5 on one game: one pick, one skip, with the rule's own reason."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        self.manual_ledger = os.path.join(self._tmp.name, "manual.jsonl")

    def classic(self):
        h = hound("u-pair1", created_at="2026-10-20T06:00:00Z", markets=["moneyline", "spread"], price_min=-199,
                  price_max=250, max_bets_per_day=5)
        return common.Dog(id=h["id"], kind=common.KIND_USER, name="Pair", hound=h, owner_user_id=OWNER, status="running",
                          root_id=h["id"])

    def english(self):
        h = RF.hound("u-pair2", created_at="2026-10-20T06:00:00Z", max_bets_per_day=5,
                     rules=[RF.rule(markets=["moneyline", "spread"], side="away", price_min=-199, price_max=250)])
        return common.Dog(id=h["id"], kind=common.KIND_USER, name="Pair2", hound=h, owner_user_id=OWNER, status="running",
                          root_id=h["id"])

    def run_batch(self, dog, order):
        picks = [{"event_id": "pair", "market": m} for m in order]
        if dog.hound["id"] == "u-pair1":
            games = fire.load_games(["MLB"], EARLY, lambda _d, _s: pair_rows())
            return manual.record_batch(dog, OWNER, picks, now=EARLY, games=games, ledger=self.manual_ledger,
                                       rule_ledger=self.ledger)
        return manual.record_batch(dog, OWNER, picks, now=EARLY, ledger=self.manual_ledger, rule_ledger=self.ledger,
                                   slate_for=_slate_for(pair_rows()))

    def check(self, dog, order):
        out = self.run_batch(dog, order)
        self.assertEqual((out["added"], out["skipped"]), (1, 1), out)
        skipped = next(r for r in out["results"] if r["status"] == "skipped")
        self.assertTrue(skipped["reason"].startswith("one side per game: "), skipped)
        self.assertEqual(len(manual_rows(self.manual_ledger)), 1)

    def test_a_classic_dog_moneyline_first(self):
        self.check(self.classic(), ["moneyline", "spread"])

    def test_a_classic_dog_spread_requested_first(self):
        self.check(self.classic(), ["spread", "moneyline"])

    def test_an_english_rules_dog(self):
        self.check(self.english(), ["moneyline", "spread"])

    def test_a_position_the_rule_ledger_already_holds_blocks_the_other_side(self):
        dog = self.classic()
        engine_dog = dict(dog.hound)
        engine_dog["spec"] = dict(engine_dog["spec"], markets=["moneyline"])
        user_engine.run("2026-10-20", [engine_dog], pair_rows(), ledger=self.ledger, now=EARLY, mode="live",
                        place_ahead=True)
        out = self.run_batch(dog, ["spread"])
        self.assertEqual((out["added"], out["skipped"]), (0, 1))
        self.assertTrue(out["reasons"][0]["reason"].startswith("one side per game: "), out)
        self.assertEqual(manual_rows(self.manual_ledger), [])


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
