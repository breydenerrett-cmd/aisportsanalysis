"""Fire now and the manual pick (src/hounds/interact/fire.py, manual.py), on fixture boards.

Needs no FastAPI and no stored data: dogs are built in memory and the boards are the user-hound fixtures
(tests/_hounds_user_fixtures.py), so the picks are worked out by hand in the comments.

THE STANDARD GAME starts 23:10Z on 2026-10-20. Captures at 19:55 (open), 21:05 (lock) and 22:20 (late). At the
lock capture the moneyline is home -140 / away +120 on five books, so the underdog is Boston at +120.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_spec
from src.hounds.interact import common, fire, manual
from tests._hounds_user_fixtures import (AWAY, BOOKS, DATE, EVENT, HOME, START, T_LOCK, board_rows, hound,
                                         standard_rows, utc)

NOW = utc("2026-10-20T21:30:00Z")          # after the lock capture, before the late one, before the start
OWNER = 7


def dog_of(status: str = "running", owner: int = OWNER, hid: str = "u-test1", **over) -> common.Dog:
    h = hound(hid, **over)
    h.update({"owner_user_id": owner, "status": status, "name": "Dog Days", "tagline": "Fetch.",
              "root_id": hid})
    return common.Dog(id=hid, kind=common.KIND_USER, name="Dog Days", tagline="Fetch.", hound=h,
                      owner_user_id=owner, status=status, root_id=hid)


def rows_for(rows):
    return lambda date, sports: iter(rows)


class Tmp(unittest.TestCase):
    def setUp(self):
        fire.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        self.manual_ledger = os.path.join(self._tmp.name, "hounds_manual_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def fire(self, dog=None, rows=None, now=NOW, **kw):
        return fire.fire_user(dog or dog_of(), now=now, rows_for=rows_for(rows if rows is not None else standard_rows()),
                              ledger=self.ledger, **kw)


class WhatItPicks(Tmp):
    def test_the_underdog_rule_picks_boston_at_the_lock_board_average_with_every_check_shown(self):
        out = self.fire()
        self.assertEqual(len(out["picks"]), 1)
        p = out["picks"][0]
        self.assertEqual((p["selection"], p["market"], p["side"]), (f"{AWAY} to win", "moneyline", "away"))
        self.assertEqual((p["price_average"], p["price_best"], p["n_books"]), (120, 120, 5))
        self.assertEqual(p["board_observed_utc"], "2026-10-20T21:05:00Z")      # the 22:20 capture is in the future
        self.assertEqual(p["board_age_minutes"], 25)
        self.assertFalse(p["stale"])
        labels = [c["label"] for c in p["checks"]]
        self.assertEqual(labels, ["Board", "Minimum books", "Side rule", "Price band", "The -200 cap"])
        self.assertTrue(all(c["ok"] for c in p["checks"]))
        self.assertIn("+120 is inside +100 to +250", p["checks"][3]["detail"])
        self.assertIn("Rule: the underdog", p["reason"])
        self.assertTrue(out["paper_only"])
        self.assertEqual(out["mode"], "preview")
        self.assertIn("preview", out["preview_note"].lower())

    def test_it_is_the_engines_own_pick_at_the_same_instant(self):
        """Parity: run the live engine at the dog's lock and fire at the same moment; same ticket."""
        out = self.fire(now=utc("2026-10-20T21:10:00Z"))
        eng.run(DATE, [hound()], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        bet = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET][0]
        p = out["picks"][0]
        for ours, theirs in ((p["selection"], bet["selection"]), (p["price_average"], bet["price"]),
                             (p["price_best"], bet["best_price"]), (p["n_books"], bet["n_books"]),
                             (p["market"], bet["market"]), (p["board_observed_utc"], bet["board_observed_utc"])):
            self.assertEqual(ours, theirs)
        # and the preview now sees that ticket as already on the record rather than picking it again
        again = self.fire(now=utc("2026-10-20T21:12:00Z"))
        self.assertEqual(again["picks"], [])
        self.assertEqual(again["recorded"][0]["selection"], bet["selection"])

    def test_firing_writes_nothing_anywhere(self):
        before = set(os.listdir(self._tmp.name))
        self.fire()
        self.fire(dog_of(side_rule="favourite", price_min=-190, price_max=-110))
        self.assertEqual(set(os.listdir(self._tmp.name)), before)
        self.assertFalse(os.path.exists(self.ledger))
        self.assertFalse(os.path.exists(self.manual_ledger))

    def test_a_game_that_has_started_is_not_read(self):
        out = self.fire(now=utc("2026-10-20T23:11:00Z"))
        self.assertEqual((out["picks"], out["games_considered"]), ([], 0))
        self.assertIn("No upcoming game", out["headline"])

    def test_a_board_older_than_the_engines_limit_is_flagged_and_refused_for_a_manual_pick(self):
        rows = board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS])
        out = self.fire(rows=rows, now=utc("2026-10-20T22:50:00Z"))
        p = out["picks"][0]
        self.assertTrue(p["stale"])
        self.assertEqual(p["board_age_minutes"], 105)
        self.assertTrue(any("older than 75" in n for n in out["notes"]))

    def test_the_daily_limit_marks_the_pick_the_engine_would_cut(self):
        # two games, one ticket a day: the earlier game is kept, the later is marked over the limit. (It used to be
        # one game's moneyline and spread; the engine now takes one side per game, so that was one ticket anyway.)
        d = dog_of(markets=["moneyline"], max_bets_per_day=1)
        second = []
        for t in ("2026-10-20T19:55:00Z", T_LOCK):
            second += board_rows(t, event_id="evt0002", home="Home Club", away="Away Club",
                                 start="2026-10-20T23:40:00Z", moneyline=[(b, -140, 120) for b in BOOKS])
        out = self.fire(d, rows=standard_rows() + second)
        self.assertEqual(len(out["picks"]), 2)
        flags = {p["event_id"]: p["over_daily_limit"] for p in out["picks"]}
        self.assertEqual(flags, {EVENT: False, "evt0002": True})
        self.assertTrue(any("daily limit" in n for n in out["notes"]))

    def test_the_preview_shows_one_side_of_a_game_like_the_engine_writes_it(self):
        d = dog_of(markets=["moneyline", "spread"], price_min=-195)
        out = self.fire(d)
        self.assertEqual([p["market"] for p in out["picks"]], ["moneyline"])

    def test_a_dog_that_is_not_running_says_so(self):
        out = self.fire(dog_of(status="benched"))
        self.assertTrue(any("benched" in n for n in out["notes"]))

    def test_other_kinds_of_dog_cannot_be_fired(self):
        other = common.Dog(id="desk", kind=common.KIND_OTHER, name="Desk")
        with self.assertRaises(fire.NotFirable):
            fire.fire(other)


class TheClosestMisses(Tmp):
    def test_a_price_outside_the_band_says_by_how_much(self):
        out = self.fire(dog_of(price_min=150, price_max=250))                  # the dog is +120: short of the band
        self.assertEqual(out["picks"], [])
        self.assertTrue(out["nothing_qualifies"])
        m = out["closest_misses"][0]
        self.assertEqual(m["code"], "outside_price_band")
        self.assertIn("+120", m["why"])
        self.assertIn("+150", m["why"])
        self.assertIn("shorter than your band", m["why"])
        # 100/220 = 45.45% against 100/250 = 40% for +150 -> hmm: prob(+120)=45.45, prob(+150)=40.0 -> 5.5 points
        self.assertAlmostEqual(m["gap"], 5.5, places=1)
        self.assertEqual(m["unit"], "points")

    def test_too_few_books_names_the_shortfall(self):
        out = self.fire(dog_of(min_books=8))
        m = out["closest_misses"][0]
        self.assertEqual(m["code"], "too_few_books")
        self.assertIn("5 books are quoting", m["why"])
        self.assertIn("at least 8", m["why"])
        self.assertEqual(m["gap"], 3.0)

    def test_the_minus_200_cap_is_named_even_for_a_favourite_rule(self):
        rows = board_rows(T_LOCK, moneyline=[(b, -250, 210) for b in BOOKS])
        out = self.fire(dog_of(side_rule="favourite", price_min=-199, price_max=-101), rows=rows)
        m = out["closest_misses"][0]
        self.assertEqual(m["code"], "price_cap")
        self.assertIn("-250", m["why"])
        self.assertIn("-200", m["why"])
        self.assertEqual(out["picks"], [])

    def test_a_movement_rule_with_nothing_to_follow_says_so(self):
        rows = board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS])   # one capture: no first board
        out = self.fire(dog_of(side_rule="market_moved_toward", price_min=-190, price_max=250), rows=rows)
        m = out["closest_misses"][0]
        self.assertEqual(m["code"], "rule_has_no_side")
        self.assertIn("only one capture", m["why"])

    def test_misses_are_ordered_nearest_first_and_the_codes_are_the_engines(self):
        # the away spread (+1.5) is -190, inside -195..110; the moneyline underdog +120 is past the long end
        d = dog_of(markets=["moneyline", "spread"], price_min=-195, price_max=110)
        out = self.fire(d)
        self.assertEqual([p["market"] for p in out["picks"]], ["spread"])
        codes = {m["market"]: m["code"] for m in out["closest_misses"]}
        self.assertEqual(codes, {"moneyline": "outside_price_band"})
        self.assertEqual(out["miss_counts"], {"outside_price_band": 1})

    def test_every_game_is_listed_with_what_the_dog_did_about_each_market(self):
        out = self.fire(dog_of(markets=["moneyline", "spread"], price_min=-195, price_max=110))
        game = out["games"][0]
        self.assertEqual(game["game"], f"{AWAY} @ {HOME}")
        status = {m["market"]: m["status"] for m in game["markets"]}
        self.assertEqual(status, {"spread": "pick", "moneyline": "miss"})


class TheManualPick(Tmp):
    def record(self, dog=None, user=OWNER, now=NOW, market="moneyline", rows=None, **kw):
        return manual.record(dog or dog_of(), user, EVENT, market, now=now, ledger=self.manual_ledger,
                             rule_ledger=self.ledger, rows_for=rows_for(rows if rows is not None else standard_rows()), **kw)

    def refused(self, code, **kw):
        with self.assertRaises(manual.ManualError) as ctx:
            self.record(**kw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def test_the_owner_records_it_in_its_own_ledger_priced_by_the_server(self):
        ticket = self.record()
        self.assertEqual((ticket["selection"], ticket["price_average"], ticket["kind"]), (f"{AWAY} to win", 120, "manual"))
        self.assertFalse(ticket["counted_in_record"])
        rows = manual.read_all(self.manual_ledger)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["manual"])
        self.assertEqual((row["provenance"], row["segment"], row["who_decided"]), ("manual", "manual", "owner"))
        self.assertTrue(row["paper_only"])
        self.assertTrue(row["bet_id"].startswith("m-"))
        self.assertIn("Manual pick by the owner", row["reason"])
        self.assertLess(user_spec.MAX_FAVOURITE_PRICE, row["price"])

    def test_it_never_reaches_the_dogs_rule_record(self):
        """The rule ledger is untouched, and the public stats read only that ledger."""
        self.record()
        self.assertFalse(os.path.exists(self.ledger))                # nothing in the user ledger
        from src.hounds import ledgers
        bets, _ = ledgers.pack_ledger_rows(self.ledger)
        self.assertEqual(bets, [])
        # and the manual ledger is a different file from the one the stats open
        self.assertNotEqual(manual.ledger_path(self.manual_ledger), eng.ledger_path())

    def test_only_the_owner(self):
        self.refused("not_owner", user=OWNER + 1)

    def test_not_for_a_house_dog_or_a_dog_that_is_not_running(self):
        house = common.Dog(id="chalk_chihuahua", kind=common.KIND_HOUSE, name="Chalk")
        with self.assertRaises(manual.ManualError) as ctx:
            manual.record(house, OWNER, EVENT, "moneyline", now=NOW, ledger=self.manual_ledger)
        self.assertEqual(ctx.exception.code, "not_a_builder_dog")
        self.refused("not_running", dog=dog_of(status="benched"))

    def test_the_game_must_not_have_started(self):
        err = self.refused("not_a_pick", now=utc("2026-10-20T23:11:00Z"))     # a started game is not on the boards
        self.assertEqual(err.status, 422)

    def test_a_pick_the_rule_would_not_make_is_refused(self):
        self.refused("not_a_pick", dog=dog_of(price_min=150, price_max=250))

    def test_a_price_off_a_stale_board_is_refused(self):
        rows = board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS])
        err = self.refused("board_too_old", now=utc("2026-10-20T22:50:00Z"), rows=rows)
        self.assertEqual(err.status, 409)

    def test_the_minus_200_guard_holds_even_if_everything_else_passes(self):
        """Hand the recorder a pick at -250 as if the evaluation had let it through: it still refuses."""
        good = fire.fire_user(dog_of(), now=NOW, rows_for=rows_for(standard_rows()), ledger=self.ledger)
        pick = dict(good["picks"][0])
        pick["row"] = dict(pick["row"], price=-250)
        with mock.patch.object(fire, "fire_user", lambda *a, **k: dict(good, picks=[pick])):
            err = self.refused("price_cap")
        self.assertEqual(err.status, 422)
        self.assertFalse(os.path.exists(self.manual_ledger))

    def test_one_manual_ticket_per_game_and_market(self):
        self.record()
        self.refused("already_on_record")

    def test_a_game_the_rule_already_has_a_ticket_on_is_refused(self):
        eng.run(DATE, [hound()], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        self.refused("already_on_record", now=utc("2026-10-20T21:12:00Z"))

    def test_five_a_day_per_dog(self):
        # five different dogs' worth of games: use five events on the same slate, each with the same board
        rows = []
        for i in range(6):
            rows += standard_rows(event_id=f"evt{i:04d}")
        for i in range(5):
            manual.record(dog_of(max_bets_per_day=5), OWNER, f"evt{i:04d}", "moneyline", now=NOW,
                          ledger=self.manual_ledger, rule_ledger=self.ledger, rows_for=rows_for(rows))
        self.assertEqual(manual.recorded_today("u-test1", NOW, self.manual_ledger), 5)
        self.assertEqual(manual.remaining_today("u-test1", NOW, self.manual_ledger), 0)
        with self.assertRaises(manual.ManualError) as ctx:
            manual.record(dog_of(max_bets_per_day=5), OWNER, "evt0005", "moneyline", now=NOW,
                          ledger=self.manual_ledger, rule_ledger=self.ledger, rows_for=rows_for(rows))
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("rate_limited", 429))
        # the next Eastern day starts a fresh count
        self.assertEqual(manual.recorded_today("u-test1", NOW + timedelta(days=1), self.manual_ledger), 0)

    def test_it_is_graded_by_the_same_grader_and_shown_apart(self):
        self.record()
        report = manual.settle_manual(now=utc("2026-10-21T12:00:00Z"), ledger=self.manual_ledger,
                                      mlb_results={"900001": {"game_pk": "900001", "date": DATE, "away_team": "BOS",
                                                              "home_team": "SEA", "away_score": "5", "home_score": "3"}},
                                      game_pk_index={EVENT: {"game_pk": "900001"}}, close_fn=lambda b: None)
        self.assertEqual(report["graded"], 1)
        items = manual.tickets("u-test1", path=self.manual_ledger, now=utc("2026-10-21T12:00:00Z"))
        self.assertEqual((items[0]["status"], items[0]["result"]), ("WON", "WIN"))
        self.assertEqual(items[0]["units_average_price"], 1.2)
        rec = manual.record_summary(items)
        self.assertEqual((rec["wins"], rec["losses"], rec["units_average_price"]), (1, 0, 1.2))
        self.assertIn("never counted", rec["note"])
        # still nothing in the rule ledger
        self.assertFalse(os.path.exists(self.ledger))


class HouseDogs(unittest.TestCase):
    """A pack dog's rule over fixture stores: the pack runner's own selection, read only."""

    def setUp(self):
        from tests.test_house_pack_hounds import START as HSTART, basic_stores
        from src.hounds import pack as pack_mod, pack_run
        from src.hounds.learning import champions
        self.stores = basic_stores()
        self.now = HSTART - timedelta(minutes=90)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_house_v1.jsonl")
        for p in (mock.patch.object(pack_run, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs))):
            p.start()
            self.addCleanup(p.stop)
        self.pack = pack_mod

    def dog(self, hid):
        h = self.pack.BY_ID[hid]
        return common.Dog(id=hid, kind=common.KIND_HOUSE, name=h.name, tagline=h.tagline, house=h, root_id=hid)

    def test_chalk_picks_the_favourite_at_the_board_average_and_says_why(self):
        out = fire.fire_house(self.dog("chalk_chihuahua"), now=self.now, stores=self.stores, recorded=set())
        self.assertEqual(len(out["picks"]), 1)
        p = out["picks"][0]
        self.assertEqual(p["selection"], "Boston Red Sox ML")
        self.assertEqual(p["price_average"], -130)
        self.assertIn("favourite", p["reason"])
        self.assertEqual(p["n_books"], 5)
        self.assertTrue(out["paper_only"])
        self.assertFalse(os.path.exists(self.ledger))                 # read only

    def test_a_dog_whose_rule_does_not_fire_names_its_trigger(self):
        out = fire.fire_house(self.dog("home_dog_hank"), now=self.now, stores=self.stores, recorded=set())
        self.assertEqual(out["picks"], [])
        m = out["closest_misses"][0]
        self.assertEqual(m["code"], "rule_not_met")
        self.assertIn("home club is a +100 to +400 underdog", m["why"])
        self.assertEqual(out["headline"], "Nothing qualifies right now.")

    def test_a_ticket_already_on_the_record_is_not_picked_again(self):
        out = fire.fire_house(self.dog("chalk_chihuahua"), now=self.now, stores=self.stores,
                              recorded={("evA", "moneyline")})
        self.assertEqual(out["picks"], [])
        self.assertEqual(out["recorded"][0]["selection"], "Boston Red Sox ML")

    def test_a_started_game_is_left_alone(self):
        from tests.test_house_pack_hounds import START as HSTART
        out = fire.fire_house(self.dog("chalk_chihuahua"), now=HSTART + timedelta(minutes=5), stores=self.stores,
                              recorded=set())
        self.assertEqual((out["picks"], out["games_considered"]), ([], 0))


if __name__ == "__main__":
    unittest.main()
