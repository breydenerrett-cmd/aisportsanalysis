"""Fire now for ONE game (src/hounds/interact/fire_event.py): picked-with-the-pick or not-picked-with-the-reason,
including a game that has started and has in-play snapshots (a live price). Fixture rows only; read only.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_engine_v2 as v2
from src.hounds import user_spec
from src.hounds.interact import common, fire, fire_event
from src.hounds.user_facts import FactBook
from tests._hounds_user_fixtures import BOOKS, DATE, EVENT, T_LOCK, board_rows, hound, utc
from tests.test_hounds_interact_fire import dog_of, rows_for

PRE_GAME = utc("2026-10-20T21:30:00Z")         # after the lock capture, before the start (23:10Z)
LIVE_NOW = utc("2026-10-20T23:40:00Z")         # 30 minutes into the game
T_LIVE = "2026-10-20T23:35:00Z"                # an in-play snapshot, 5 minutes old at LIVE_NOW


def tag(rows, league="basketball_nba", in_play=False):
    for r in rows:
        r["league"], r["league_title"] = league, "NBA"
        if in_play:
            r["in_play"] = True
    return rows


def pregame(price=(-140, 120)):
    return tag(board_rows(T_LOCK, home="Boston Celtics", away="New York Knicks", sport="nba",
                          moneyline=[(b, price[0], price[1]) for b in BOOKS]))


def live(price=(-300, 250), observed=T_LIVE):
    return tag(board_rows(observed, home="Boston Celtics", away="New York Knicks", sport="nba",
                          moneyline=[(b, price[0], price[1]) for b in BOOKS]), in_play=True)


def nba_dog(**over):
    over.setdefault("sports", ["NBA"])
    over.setdefault("price_min", 100)
    over.setdefault("price_max", 400)
    return dog_of(**over)


def v2_nba_dog():
    spec = user_spec.validate_spec({
        "version": 2, "name": "Live Dog", "lock_minutes": 120, "max_bets_per_day": 2, "rules": [
            {"sports": ["NBA"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 400,
             "min_books": 3, "when": {"op": "all", "items": [{"id": "role", "value": "underdog"}]}}]})
    h = {"id": "u-v2n", "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": "2026-01-01T00:00:00Z",
         "owner_user_id": 7, "status": "running", "name": "Live Dog", "tagline": "", "root_id": "u-v2n"}
    return common.Dog(id="u-v2n", kind=common.KIND_USER, name="Live Dog", hound=h, owner_user_id=7,
                      status="running", root_id="u-v2n")


class Base(unittest.TestCase):
    def setUp(self):
        fire.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "l.jsonl")
        patcher = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, dog, rows, now, event_id=EVENT):
        return fire_event.answer(dog, event_id, now=now, rows_for=rows_for(rows), ledger=self.ledger,
                                 slate_for=self.slate_for(rows))

    def slate_for(self, rows):
        def slate_for(date, with_props):
            return v2.build_slate(date, ["NBA"], with_props=with_props, rows=list(rows), prop_rows=[],
                                  facts=FactBook(), game_pk_index={})
        return slate_for


class BeforeTheStart(Base):
    def test_a_qualifying_game_is_picked_with_the_pick(self):
        out = self.ask(nba_dog(), pregame(), PRE_GAME)
        self.assertTrue(out["picked"])
        self.assertFalse(out["live"])
        self.assertEqual(out["event_id"], EVENT)
        self.assertEqual((out["pick"]["selection"], out["pick"]["price_average"], out["pick"]["sport"]),
                         ("New York Knicks to win", 120, "NBA"))
        self.assertEqual(out["code"], "pick")
        self.assertTrue(out["reason"])
        self.assertTrue(out["paper_only"])

    def test_a_game_the_dog_skips_says_why_in_the_engines_own_code(self):
        out = self.ask(nba_dog(price_min=300, price_max=500), pregame(), PRE_GAME)
        self.assertFalse(out["picked"])
        self.assertIsNone(out["pick"])
        self.assertEqual(out["code"], "outside_price_band")
        self.assertIn("band", out["reason"])

    def test_a_game_already_on_the_record_is_picked_and_marked_recorded(self):
        dog = nba_dog()
        eng.run(DATE, [dog.hound], pregame(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        out = self.ask(dog, pregame(), PRE_GAME)
        self.assertTrue(out["picked"])
        self.assertTrue(out["recorded"])

    def test_an_unknown_event_is_not_picked(self):
        out = self.ask(nba_dog(), pregame(), PRE_GAME, event_id="nope")
        self.assertEqual((out["picked"], out["code"]), (False, "unknown_event"))

    def test_an_event_of_a_sport_the_dog_does_not_bet_is_not_eligible(self):
        out = self.ask(dog_of(sports=["MLB"]), pregame(), PRE_GAME)
        self.assertEqual((out["picked"], out["code"], out["sport"]), (False, "not_eligible", "NBA"))


class InPlay(Base):
    def rows(self, **kw):
        return pregame() + live(**kw)

    def test_a_started_game_is_read_on_its_newest_in_play_price(self):
        out = self.ask(nba_dog(), self.rows(price=(-300, 250)), LIVE_NOW)
        self.assertTrue(out["picked"])
        self.assertTrue(out["live"])
        pick = out["pick"]
        self.assertEqual((pick["selection"], pick["price_average"]), ("New York Knicks to win", 250))   # not the +120 pre-game
        self.assertTrue(pick["live"] and pick["in_play"])
        self.assertEqual(pick["board_observed_utc"], T_LIVE)
        self.assertEqual(pick["board_age_minutes"], 5.0)

    def test_the_dogs_band_still_decides_on_the_live_price(self):
        out = self.ask(nba_dog(price_min=100, price_max=200), self.rows(price=(-300, 250)), LIVE_NOW)
        self.assertFalse(out["picked"])
        self.assertTrue(out["live"])
        self.assertEqual(out["code"], "outside_price_band")

    def test_the_minus_200_cap_holds_on_a_live_price(self):
        out = self.ask(nba_dog(side_rule="favourite", price_min=-199, price_max=150),
                       self.rows(price=(-1260, 700)), LIVE_NOW)
        self.assertFalse(out["picked"])
        self.assertEqual(out["code"], "price_cap")

    def test_a_started_game_with_only_pre_game_prices_has_no_live_price(self):
        out = self.ask(nba_dog(), pregame(), LIVE_NOW)
        self.assertEqual((out["picked"], out["code"]), (False, "no_live_price"))

    def test_a_live_price_older_than_ninety_minutes_is_refused(self):
        out = self.ask(nba_dog(), self.rows(), utc("2026-10-21T01:30:00Z"))          # snapshot is 115 minutes old
        self.assertEqual((out["picked"], out["code"]), (False, "live_price_too_old"))

    def test_a_game_past_its_live_window_is_over(self):
        out = self.ask(nba_dog(), self.rows(), utc("2026-10-21T03:00:00Z"))
        self.assertEqual((out["picked"], out["code"]), (False, "game_over"))

    def test_nothing_is_written_anywhere(self):
        self.ask(nba_dog(), self.rows(), LIVE_NOW)
        self.assertFalse(os.path.exists(self.ledger))

    def test_a_dog_built_from_english_rules_is_answered_on_the_live_price_too(self):
        out = self.ask(v2_nba_dog(), self.rows(price=(-300, 250)), LIVE_NOW)
        self.assertTrue(out["picked"], out)
        self.assertTrue(out["live"])
        self.assertEqual((out["pick"]["selection"], out["pick"]["price_average"]), ("New York Knicks to win", 250))

    def test_an_english_dog_that_skips_says_why(self):
        # both sides at -110: there is no underdog, so the role condition cannot hold
        out = self.ask(v2_nba_dog(), self.rows(price=(-110, -110)), LIVE_NOW)
        self.assertFalse(out["picked"])
        self.assertTrue(out["live"])
        self.assertTrue(out["reason"])
        self.assertIn(out["code"], ("rule_not_met", "outside_price_band"))


class HouseDogsAreNotEvaluatedLive(Base):
    def test_an_unknown_event_for_a_house_dog_says_so(self):
        from src.hounds import pack as pack_mod
        h = pack_mod.BY_ID["chalk_chihuahua"]
        dog = common.Dog(id=h.id, kind=common.KIND_HOUSE, name=h.name, tagline=h.tagline, house=h, root_id=h.id)
        with mock.patch.object(fire, "fire", return_value={"picks": [], "recorded": [], "games": [],
                                                           "closest_misses": []}):
            out = fire_event.answer(dog, "zzz", now=PRE_GAME)
        self.assertEqual((out["picked"], out["code"]), (False, "unknown_event"))


class TheEmptyResultLines(Base):
    """The two plain-string fields the page reads when the fire result has no picks."""

    TUESDAY = utc("2026-10-20T14:00:00Z")           # 10 am Eastern; the standard game is tonight

    def fire_empty(self, other_live=None, **dog_over):
        dog = nba_dog(price_min=300, price_max=500, **dog_over)            # a band nothing meets: no pick
        return fire.fire_user(dog, now=self.TUESDAY, rows_for=rows_for(pregame()), ledger=self.ledger,
                              other_live=other_live)

    def test_no_picks_carries_the_next_game_and_what_is_live_elsewhere_as_strings(self):
        other = lambda own, at: {"games": 14, "families": [], "text": "Live now in other sports: 14 games (tennis, cricket)."}  # noqa: E731
        out = self.fire_empty(other)
        self.assertEqual(out["picks"], [])
        self.assertEqual(out["next_game"], "Next game: Tue 7:10 PM — New York Knicks at Boston Celtics")
        self.assertEqual(out["live_elsewhere"], "Live now in other sports: 14 games (tennis, cricket)")

    def test_a_pick_means_neither_line(self):
        other = lambda own, at: {"games": 14, "families": [], "text": "Live now in other sports: 14 games (tennis)."}  # noqa: E731
        dog = nba_dog()
        out = fire.fire_user(dog, now=PRE_GAME, rows_for=rows_for(pregame()), ledger=self.ledger, other_live=other)
        self.assertEqual(len(out["picks"]), 1)
        self.assertIsNone(out["next_game"])
        self.assertIsNone(out["live_elsewhere"])

    def test_nothing_live_elsewhere_and_no_game_ahead_leave_the_fields_empty(self):
        dog = nba_dog()
        out = fire.fire_user(dog, now=self.TUESDAY, rows_for=rows_for([]), ledger=self.ledger,
                             other_live=lambda own, at: {"games": 0, "families": [], "text": ""})
        self.assertIsNone(out["next_game"])
        self.assertIsNone(out["live_elsewhere"])

    def test_the_lines_are_given_even_when_the_dog_has_a_game_later_today(self):
        # a game tonight that the dog's band rejects: nothing qualifies, but there IS a next game
        out = self.fire_empty(lambda own, at: {"games": 2, "families": [], "text": "Live now in other sports: 2 games (nba)."})
        self.assertTrue(out["next_game"].startswith("Next game: Tue "))
        self.assertEqual(out["live_elsewhere"], "Live now in other sports: 2 games (nba)")

    def test_an_english_dog_gets_the_same_two_lines(self):
        other = lambda own, at: {"games": 3, "families": [], "text": "Live now in other sports: 3 games (soccer)."}  # noqa: E731
        dog = v2_nba_dog()
        out = fire.fire(dog, now=self.TUESDAY, slate_for=self.slate_for([]), ledger=self.ledger, other_live=other)
        self.assertEqual(out["picks"], [])
        self.assertIsNone(out["next_game"])
        self.assertEqual(out["live_elsewhere"], "Live now in other sports: 3 games (soccer)")

    def test_the_next_game_line_formats_in_eastern_time(self):
        upcoming = [("B @ A", utc("2026-10-22T21:15:00Z"), None), ("D @ C", utc("2026-10-23T00:15:00Z"), None)]
        self.assertEqual(fire.next_game_line(self.TUESDAY, upcoming), "Next game: Thu 5:15 PM — B at A")
        self.assertIsNone(fire.next_game_line(self.TUESDAY, []))
        self.assertIsNone(fire.next_game_line(utc("2026-10-25T00:00:00Z"), upcoming))


try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ThePostBody(unittest.TestCase):
    """api/hounds_interact.py fire_now: an optional {event_id} body answers for that game alone."""

    def setUp(self):
        from fastapi import Response
        from api import hounds_interact as api
        self.api, self.response = api, Response()
        patcher = mock.patch.object(common, "resolve", lambda i: dog_of(hid=i))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def data(out):
        return out["data"] if "data" in out else out

    def test_no_body_is_the_ordinary_fire_result(self):
        with mock.patch.object(self.api, "_fire_payload", return_value={"picks": []}) as full, \
                mock.patch.object(fire_event, "answer") as one:
            out = self.api.fire_now("u-test1", self.response, body=None, authorization=None, _rl=None)
        full.assert_called_once()
        one.assert_not_called()
        self.assertEqual(self.data(out)["picks"], [])

    def test_a_body_with_an_event_id_returns_the_per_event_answer(self):
        answer = {"event_id": "evt1", "picked": False, "code": "outside_price_band", "reason": "x", "pick": None,
                  "picks": []}
        with mock.patch.object(fire_event, "answer", return_value=answer) as one, \
                mock.patch.object(self.api, "_fire_payload") as full:
            out = self.api.fire_now("u-test1", self.response, body=self.api.FireRequest(event_id="evt1"),
                                    authorization=None, _rl=None)
        full.assert_not_called()
        self.assertEqual(one.call_args.args[1], "evt1")
        data = self.data(out)
        self.assertEqual((data["event_id"], data["picked"], data["code"]), ("evt1", False, "outside_price_band"))

    def test_an_empty_event_id_is_a_422(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.api.fire_now("u-test1", self.response, body=self.api.FireRequest(event_id="  "),
                              authorization=None, _rl=None)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_a_body_without_an_event_id_is_the_ordinary_result(self):
        with mock.patch.object(self.api, "_fire_payload", return_value={"picks": []}) as full:
            self.api.fire_now("u-test1", self.response, body=self.api.FireRequest(), authorization=None, _rl=None)
        full.assert_called_once()


if __name__ == "__main__":
    unittest.main()
