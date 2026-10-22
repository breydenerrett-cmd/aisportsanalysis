"""src/hounds/interact/unleash.py and the engine's ``place_ahead`` mode: Unleash starts a hound betting TODAY and shows
what it would have taken before it started.

The fixture day is 2026-10-20 and "now" is 18:00Z (14:00 Eastern), a 120-minute lock:

  fin      started 15:10Z, finished (Boston won).  Lock-time board 12:50Z: away +120.  A post-lock board at 14:30Z says
           away +130 (planted: the "before" list must say +120).
  late     started 15:40Z.  The lock-time board has no side to back (pick'em); a post-lock board at 14:30Z would qualify
           (planted: it must NOT be used, so the game is not in the list).
  play     in play since 17:10Z.  Lock-time board 14:50Z: away +130.
  noboard  started 17:40Z.  Its only capture is 16:30Z, AFTER its 15:40Z lock: "no board saved for this game".
  ahead1/2 start 23:10Z / 23:40Z: not locked yet.  Boards at 17:30Z: away +125 / +140.

Nothing here reads a live store: rows, results, facts and the ledger are injected.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from src.hounds import user_defs, user_engine, user_settle, user_view
from src.hounds.interact import common, fire, manual, unleash
from tests import _hounds_rules_fixtures as RF
from tests._hounds_user_fixtures import BOOKS, DATE, board_rows, hound, result_row, utc

NOW = utc("2026-10-20T18:00:00Z")
OWNER = 7
PK = {"fin": "900101"}
INDEX = {"fin": {"game_pk": PK["fin"]}}
HOME, AWAY = "Seattle Mariners", "Boston Red Sox"


def ml(away_price, home_price):
    return [(b, home_price, away_price) for b in BOOKS]


def game(event, observed, away_price, home_price, start, home=HOME, away=AWAY):
    return board_rows(observed, event_id=event, home=home, away=away, start=start, moneyline=ml(away_price, home_price))


def day_rows():
    rows = []
    rows += game("fin", "2026-10-20T12:50:00Z", 120, -140, "2026-10-20T15:10:00Z", "Texas Rangers", "Detroit Tigers")
    rows += game("fin", "2026-10-20T14:30:00Z", 130, -150, "2026-10-20T15:10:00Z", "Texas Rangers", "Detroit Tigers")   # after the lock
    rows += game("late", "2026-10-20T12:50:00Z", -110, -110, "2026-10-20T15:40:00Z", "Houston Astros", "Oakland Athletics")
    rows += game("late", "2026-10-20T14:30:00Z", 150, -170, "2026-10-20T15:40:00Z", "Houston Astros", "Oakland Athletics")  # after the lock
    rows += game("play", "2026-10-20T14:50:00Z", 130, -150, "2026-10-20T17:10:00Z", "Chicago Cubs", "Miami Marlins")
    rows += game("noboard", "2026-10-20T16:30:00Z", 125, -145, "2026-10-20T17:40:00Z", "Atlanta Braves", "New York Mets")
    rows += game("ahead1", "2026-10-20T17:30:00Z", 125, -145, "2026-10-20T23:10:00Z", HOME, AWAY)
    rows += game("ahead2", "2026-10-20T17:30:00Z", 140, -160, "2026-10-20T23:40:00Z", "Cleveland Guardians", "Toronto Blue Jays")
    return rows


def results():
    return {PK["fin"]: result_row(PK["fin"], DATE, "DET", "TEX", 4, 2)}


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        self.manual_ledger = os.path.join(self._tmp.name, "manual.jsonl")
        self.refreshed = []

    def dog(self, h=None, **over):
        h = h or hound("u-unl1", created_at="2026-10-20T06:00:00Z", max_bets_per_day=5, **over)
        return common.Dog(id=h["id"], kind=common.KIND_USER, name=h["spec"]["name"], hound=h, owner_user_id=OWNER,
                          status="running", root_id=h["id"])

    def go(self, dog=None, *, now=NOW, rows=None, **kw):
        kw.setdefault("mlb_results", results())
        kw.setdefault("nfl_results", lambda _d: {})
        kw.setdefault("allsports_results", {})
        kw.setdefault("facts", object())             # a classic dog never reads facts
        return unleash.unleash(dog or self.dog(), OWNER, now=now, rows=day_rows() if rows is None else rows,
                               ledger=self.ledger, game_pk_index=INDEX, refresh_stats=lambda: self.refreshed.append(1),
                               manual_ledger=self.manual_ledger, **kw)

    def bets(self):
        return [r for r in user_engine.read_ledger(self.ledger) if r.get("kind") == user_engine.KIND_BET]


class StartsTheHoundToday(_Case):
    def test_it_places_todays_not_yet_locked_qualifying_bets_through_the_engine(self):
        out = self.go()
        self.assertFalse(out["already_running"])
        self.assertEqual(out["placed_now"], 2)
        self.assertEqual((out["games_on_board"], out["games_ahead"], out["games_before"]), (6, 2, 4))
        self.assertEqual([p["event_id"] for p in out["picks"]], ["ahead1", "ahead2"])
        first = out["picks"][0]
        self.assertEqual((first["game"], first["selection"], first["price_average"], first["stake_units"]),
                         ("Boston Red Sox @ Seattle Mariners", "Boston Red Sox to win", 125, 1.0))
        self.assertNotIn("stake_usd", first)               # dollars are the viewer's lens (web/js/unitsize.js), never the server's $10
        self.assertTrue(first["placed_now"] and first["on_record"])
        rows = self.bets()
        self.assertEqual(sorted(r["event_id"] for r in rows), ["ahead1", "ahead2"])
        for row in rows:                                  # priced on the board as of NOW (17:30Z), the lock is still ahead
            self.assertEqual(row["board_observed_utc"], "2026-10-20T17:30:00Z")
            self.assertEqual(row["recorded_utc"], "2026-10-20T18:00:00Z")
            self.assertTrue(row["lock_utc"] > row["recorded_utc"])
            self.assertTrue(row["paper_only"])
        self.assertEqual(self.refreshed, [1])             # the public numbers are told

    def test_a_second_tap_places_nothing_and_just_shows_the_day(self):
        self.go()
        before = open(self.ledger, "rb").read()
        again = self.go()
        self.assertTrue(again["already_running"])
        self.assertEqual(again["placed_now"], 0)
        self.assertEqual([p["event_id"] for p in again["picks"]], ["ahead1", "ahead2"])
        self.assertTrue(all(not p["placed_now"] for p in again["picks"]))
        self.assertEqual(open(self.ledger, "rb").read(), before)       # byte for byte: not one row added
        self.assertEqual(self.refreshed, [1])

    def test_the_normal_runner_finds_the_bets_already_written_and_adds_nothing(self):
        self.go()
        h = self.dog().hound
        later = utc("2026-10-20T21:20:00Z")               # past ahead1's lock
        report = user_engine.run(DATE, [h], day_rows(), ledger=self.ledger, now=later, mode="live", game_pk_index=INDEX)
        self.assertEqual(report["bets_written"], 0)
        self.assertEqual(len(self.bets()), 2)

    def test_a_game_that_has_started_is_never_placed_as_a_bet(self):
        out = self.go()
        placed = {r["event_id"] for r in self.bets()}
        for started in ("fin", "late", "play", "noboard"):
            self.assertNotIn(started, placed)
        self.assertTrue(all(not p["started"] for p in out["picks"]))
        # and the engine's own guard, asked directly with a clock past ahead1's start
        os.remove(self.ledger)
        user_engine.run(DATE, [self.dog().hound], day_rows(), ledger=self.ledger, now=utc("2026-10-20T23:20:00Z"),
                        mode="live", game_pk_index=INDEX, place_ahead=True)
        self.assertNotIn("ahead1", {r["event_id"] for r in self.bets()})

    def test_without_place_ahead_the_normal_pass_still_waits_for_the_lock(self):
        report = user_engine.run(DATE, [self.dog().hound], day_rows(), ledger=self.ledger, now=NOW, mode="live",
                                 game_pk_index=INDEX)
        self.assertEqual(report["bets_written"], 0)
        self.assertGreaterEqual(report["skipped"].get("not_locked_yet", 0), 2)

    def test_the_daily_limit_is_the_engines(self):
        out = self.go(self.dog(hound("u-unl2", created_at="2026-10-20T06:00:00Z", max_bets_per_day=1)))
        self.assertEqual(out["placed_now"], 1)
        self.assertEqual(len(self.bets()), 1)
        self.assertEqual(out["max_bets_per_day"], 1)

    def test_never_minus_200_or_worse_not_even_for_a_hand_edited_rule(self):
        h = hound("u-unl3", created_at="2026-10-20T06:00:00Z", side_rule="favourite", price_min=-150, price_max=-100,
                  max_bets_per_day=5)
        h = deepcopy(h)
        h["spec"]["price_min"] = -400                      # a stored spec that skipped validation
        rows = []
        rows += game("ahead1", "2026-10-20T17:30:00Z", 210, -250, "2026-10-20T23:10:00Z")
        rows += game("fin", "2026-10-20T12:50:00Z", 190, -250, "2026-10-20T15:10:00Z", "Texas Rangers", "Detroit Tigers")
        rows += game("play", "2026-10-20T14:50:00Z", 150, -200, "2026-10-20T17:10:00Z", "Chicago Cubs", "Miami Marlins")
        out = self.go(self.dog(h), rows=rows)
        everything = out["picks"] + out["before"]
        self.assertEqual(everything, [])
        self.assertEqual(self.bets(), [])
        # ... and a -190 favourite is still allowed, so the cap is a cap and not a blanket refusal
        rows = game("ahead1", "2026-10-20T17:30:00Z", 170, -190, "2026-10-20T23:10:00Z")
        out = self.go(self.dog(h), rows=rows)
        self.assertEqual([p["price_average"] for p in out["picks"]], [-190])
        self.assertTrue(all(p["price_average"] > -200 for p in out["picks"] + out["before"]))

    def test_the_stake_is_the_dogs_own(self):
        out = self.go(self.dog(hound("u-unl4", created_at="2026-10-20T06:00:00Z", max_bets_per_day=5)))
        self.assertEqual({p["stake_units"] for p in out["picks"]}, {1.0})

    def test_only_the_owner_of_a_running_dog_can_unleash_it(self):
        with self.assertRaises(unleash.UnleashError) as ctx:
            unleash.unleash(self.dog(), OWNER + 1, now=NOW, rows=[], ledger=self.ledger)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_found", 404))
        buried = self.dog()
        buried.status = "buried"
        with self.assertRaises(unleash.UnleashError) as ctx:
            unleash.unleash(buried, OWNER, now=NOW, rows=[], ledger=self.ledger)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_running", 409))
        house = common.Dog(id="chalk_chihuahua", kind=common.KIND_HOUSE, name="Chalk", owner_user_id=None)
        with self.assertRaises(unleash.UnleashError):
            unleash.unleash(house, OWNER, now=NOW, rows=[], ledger=self.ledger)
        self.assertFalse(os.path.exists(self.ledger))


class BeforeYouUnleashed(_Case):
    def test_it_lists_what_the_rule_would_have_taken_on_games_already_locked(self):
        out = self.go()
        by = {b["event_id"]: b for b in out["before"]}
        self.assertEqual(sorted(by), ["fin", "play"])
        self.assertEqual(out["before_label"], "Before you unleashed. Not on its record.")
        fin, play = by["fin"], by["play"]
        self.assertEqual((fin["state"], fin["result"], fin["outcome"]), ("finished", "won", "Would have won"))
        self.assertEqual((play["state"], play["result"]), ("in_play", None))
        self.assertEqual(play["price_average"], 130)
        self.assertTrue(all(not b["counted_in_record"] for b in out["before"]))

    def test_a_loss_reads_would_have_lost(self):
        out = self.go(mlb_results={PK["fin"]: result_row(PK["fin"], DATE, "DET", "TEX", 1, 3)})
        fin = next(b for b in out["before"] if b["event_id"] == "fin")
        self.assertEqual((fin["result"], fin["outcome"]), ("lost", "Would have lost"))

    def test_only_the_board_at_each_games_own_lock_is_used_a_later_price_is_ignored(self):
        out = self.go()
        fin = next(b for b in out["before"] if b["event_id"] == "fin")
        self.assertEqual(fin["price_average"], 120)                            # not the planted +130 at 14:30Z
        self.assertEqual(fin["board_observed_utc"], "2026-10-20T12:50:00Z")
        # the game whose ONLY qualifying board came after the lock is not in the list at all
        self.assertNotIn("late", {b["event_id"] for b in out["before"]})
        # and re-planting an even better post-lock price changes nothing
        rows = day_rows() + game("fin", "2026-10-20T14:55:00Z", 240, -300, "2026-10-20T15:10:00Z", "Texas Rangers", "Detroit Tigers")
        os.remove(self.ledger)                                    # a fresh start, so it is not "already running"
        again = self.go(rows=rows)
        self.assertEqual(next(b for b in again["before"] if b["event_id"] == "fin")["price_average"], 120)

    def test_a_game_with_no_board_before_its_lock_says_so_and_is_never_guessed(self):
        out = self.go()
        self.assertEqual([g["event_id"] for g in out["no_board"]], ["noboard"])
        self.assertEqual(out["no_board"][0]["note"], "no board saved for this game")
        self.assertEqual(out["no_board_note"], "no board saved for this game")
        self.assertNotIn("noboard", {b["event_id"] for b in out["before"]})

    def test_before_picks_never_reach_the_ledger_the_record_or_the_bankroll(self):
        out = self.go()
        before_ids = {b["bet_id"] for b in out["before"]}
        self.assertTrue(before_ids)
        rows = user_engine.read_ledger(self.ledger)
        self.assertFalse(before_ids & {r.get("bet_id") for r in rows})
        self.assertEqual({r["event_id"] for r in rows if r["kind"] == user_engine.KIND_BET}, {"ahead1", "ahead2"})
        self.assertEqual([r["kind"] for r in rows if r["kind"] != user_engine.KIND_BET], [])     # no grade rows either
        record = user_settle.records_by_hound(rows)["u-unl1"]["record"]
        self.assertEqual((record["bets"], record["wins"], record["losses"]), (2, 0, 0))
        h = self.dog().hound
        defn = user_defs.definition({**h, "name": h["spec"]["name"], "owner_user_id": OWNER, "root_id": h["id"],
                                    "version_no": 1, "status": "running", "tagline": "", "retire_reason": None})
        summary = user_view._from_ledger(defn, rows).summary
        self.assertEqual((summary.record.wins, summary.record.losses, summary.record.units_average_price), (0, 0, None))
        self.assertEqual((summary.bankroll["current"], summary.bankroll["settled"], summary.bankroll["pnl_usd"]),
                         (1000.0, 0, 0.0))                   # the finished "would have won" is nowhere in the account
        # a second tap, which only SHOWS the before list, leaves the file exactly as it was
        snapshot = open(self.ledger, "rb").read()
        self.go()
        self.assertEqual(open(self.ledger, "rb").read(), snapshot)

    def test_a_dog_with_nothing_placed_leaves_no_ledger_file_at_all(self):
        rows = [r for r in day_rows() if r["event_id"] not in ("ahead1", "ahead2")]
        out = self.go(rows=rows)
        self.assertEqual(out["picks"], [])
        self.assertTrue(out["before"])
        self.assertFalse(os.path.exists(self.ledger))

    def test_a_dog_that_has_already_bet_is_only_shown_the_games_that_locked_before_it_existed(self):
        h = hound("u-unl5", created_at="2026-10-20T14:00:00Z", max_bets_per_day=5)       # born 14:00Z
        out = self.go(self.dog(h))
        self.assertEqual({p["event_id"] for p in out["picks"]}, {"ahead1", "ahead2"})
        # fin (lock 13:10Z) locked before it existed: before.  play (lock 15:10Z) locked while it existed: the live
        # pass placed it at its lock board, as a late engine pass would, so it is on the record and not "before".
        again = self.go(self.dog(h))
        self.assertTrue(again["already_running"])
        self.assertEqual({b["event_id"] for b in again["before"]}, {"fin"})

    def test_nothing_in_the_response_is_html(self):
        rows = game("ahead1", "2026-10-20T17:30:00Z", 125, -145, "2026-10-20T23:10:00Z", "<b>Mariners</b>", "A&B <i>Sox</i>")
        out = self.go(rows=rows)
        self.assertEqual(out["picks"][0]["game"], "A&B <i>Sox</i> @ <b>Mariners</b>")
        json.dumps(out)                                           # plain data, JSON all the way down


def manual_rows(path):
    return [r for r in manual.read_all(path) if r.get("kind") == user_engine.KIND_BET]


class AddTheOthersAsManualPicks(_Case):
    """The Unleash panel's "Add the other N as manual picks": the picks the rule makes that were not placed (over the day's
    limit, a later day) go to the owner's MANUAL ledger in one request, through the same ``manual.record`` as a single pick."""

    def setUp(self):
        super().setUp()
        self.dog_ = self.dog(hound("u-unl9", created_at="2026-10-20T06:00:00Z", max_bets_per_day=1))

    def day(self, **kw):
        return self.go(self.dog_, **kw)

    def games(self):
        return fire.load_games(["MLB"], NOW, lambda _d, _s: day_rows())

    def batch(self, picks, **kw):
        return manual.record_batch(self.dog_, OWNER, picks, now=NOW, games=self.games(), ledger=self.manual_ledger,
                                   rule_ledger=self.ledger, **kw)

    def test_the_unplaced_picks_are_listed_with_why_and_the_placed_one_is_not(self):
        out = self.day()
        self.assertEqual([p["event_id"] for p in out["picks"]], ["ahead1"])             # the one the day's limit allows
        other = out["other_picks"]
        self.assertEqual([o["event_id"] for o in other], ["ahead2"])
        self.assertEqual((other[0]["why_not_placed"], other[0]["can_record"], other[0]["blocked"]), ("over_limit", True, None))
        self.assertEqual((other[0]["stake_units"], other[0]["price_average"]), (1.0, 140))
        self.assertEqual(out["manual_remaining_today"], 5)
        self.assertEqual(manual_rows(self.manual_ledger), [])                           # listing adds nothing

    def test_a_batch_adds_each_pick_once_to_the_manual_ledger_and_a_second_tap_adds_nothing(self):
        out = self.day()
        picks = [{"event_id": o["event_id"], "market": o["market"]} for o in out["other_picks"]]
        rule_before = open(self.ledger, "rb").read()
        first = self.batch(picks)
        self.assertEqual((first["added"], first["skipped"], first["line"]), (1, 0, "Added 1"))
        rows = manual_rows(self.manual_ledger)
        self.assertEqual([(r["event_id"], r["manual"], r["provenance"]) for r in rows], [("ahead2", True, "manual")])
        self.assertEqual(open(self.ledger, "rb").read(), rule_before)                   # never the dog's own record
        again = self.batch(picks)
        self.assertEqual((again["added"], again["skipped"]), (0, 1))
        self.assertEqual(again["reasons"][0]["reason"], "already recorded as a manual pick")
        self.assertEqual(len(manual_rows(self.manual_ledger)), 1)
        self.assertEqual(self.day()["other_picks"][0]["blocked"], "already recorded as a manual pick")

    def test_picks_that_cannot_be_added_are_skipped_with_a_reason_and_counted(self):
        self.day()
        out = self.batch([{"event_id": "ahead2", "market": "moneyline"},
                          {"event_id": "ahead1", "market": "moneyline"},             # the rule's own bet is on the record
                          {"event_id": "play", "market": "moneyline"},               # started at 17:10Z
                          {"event_id": "fin", "market": "moneyline"},                # finished
                          {"event_id": "nope", "market": "moneyline"}])              # not on any board
        self.assertEqual((out["requested"], out["added"], out["skipped"]), (5, 1, 4))
        by = {r["reason"]: r["count"] for r in out["reasons"]}
        self.assertEqual(by, {"already on its record": 1, "game already started": 2, "no longer fits the rule on the latest board": 1})
        self.assertEqual({r["event_id"] for r in manual_rows(self.manual_ledger)}, {"ahead2"})
        self.assertNotIn("play", {r["event_id"] for r in manual_rows(self.manual_ledger)})     # never a started game
        self.assertTrue(out["line"].startswith("Added 1 · skipped 4 ("))

    def test_a_started_game_is_never_added_even_when_it_is_the_only_pick(self):
        out = self.batch([{"event_id": "play", "market": "moneyline"}])
        self.assertEqual((out["added"], out["line"]), (0, "Added 0 · skipped 1 (game already started)"))
        self.assertEqual(manual_rows(self.manual_ledger), [])

    def test_the_one_side_per_game_guard_in_record_is_respected_and_spoken_in_its_own_words(self):
        self.day()
        real = manual.record

        def guarded(dog, user_id, event_id, market, **kw):
            if event_id == "ahead2":
                raise manual.ManualError("one_side_per_game", "already on the other side of this game", 409)
            return real(dog, user_id, event_id, market, **kw)
        from unittest import mock
        with mock.patch.object(manual, "record", guarded):
            out = self.batch([{"event_id": "ahead2", "market": "moneyline"}])
        self.assertEqual((out["added"], out["skipped"]), (0, 1))
        self.assertEqual(out["line"], "Added 0 · skipped 1 (already on the other side of this game)")
        self.assertEqual(manual_rows(self.manual_ledger), [])

    def test_only_the_owner_a_running_dog_and_a_sane_list(self):
        with self.assertRaises(manual.ManualError) as ctx:
            manual.record_batch(self.dog_, OWNER + 1, [{"event_id": "ahead2", "market": "moneyline"}], now=NOW, games={})
        self.assertEqual(ctx.exception.code, "not_owner")
        with self.assertRaises(manual.ManualError) as ctx:
            self.batch([])
        self.assertEqual(ctx.exception.code, "no_picks")
        with self.assertRaises(manual.ManualError) as ctx:
            self.batch([{"event_id": f"e{i}", "market": "moneyline"} for i in range(manual.MAX_BATCH + 1)])
        self.assertEqual(ctx.exception.code, "too_many")
        with self.assertRaises(manual.ManualError) as ctx:
            self.batch([{"event_id": "", "market": "moneyline"}])
        self.assertEqual(ctx.exception.code, "pick_invalid")

    def test_duplicates_in_one_request_count_once(self):
        out = self.batch([{"event_id": "ahead2", "market": "moneyline"}] * 3)
        self.assertEqual((out["requested"], out["added"]), (1, 1))


class RuleSetDogs(unittest.TestCase):
    """A version-2 (English rules) dog goes through the same engine, with the same ``place_ahead`` mode."""

    def test_a_rules_dog_is_started_before_its_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "l.jsonl")
            h = RF.hound("u-v2unl", created_at="2026-10-20T06:00:00Z", rules=[RF.rule(side="away", price_min=100, price_max=250)])
            dog = common.Dog(id=h["id"], kind=common.KIND_USER, name=h["spec"]["name"], hound=h, owner_user_id=OWNER,
                             status="running", root_id=h["id"])
            early = utc("2026-10-20T20:00:00Z")               # lock is 21:10Z
            players = RF.patch_players()
            players.start()
            try:
                out = unleash.unleash(dog, OWNER, now=early, rows=RF.standard_rows(), ledger=ledger, game_pk_index=RF.PK_INDEX,
                                      facts=RF.facts(), prop_rows=[], mlb_results={}, nfl_results=lambda _d: {},
                                      allsports_results={}, refresh_stats=lambda: None)
            finally:
                players.stop()
            self.assertEqual(out["placed_now"], 1)
            self.assertEqual(out["picks"][0]["selection"], "Boston Red Sox to win")
            rows = [r for r in user_engine.read_ledger(ledger) if r["kind"] == user_engine.KIND_BET]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["recorded_utc"], "2026-10-20T20:00:00Z")


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
