"""Ask runs the dog's RULES (src/hounds/interact/ask.py, ask_eval.py), on fixture boards and a fixed clock.

THE STORY (owner, 2026-10-19). A member dog with no recorded ticket was asked "What bets would yopu have taken
today pre market" and said "I have not recorded a ticket yet, so there is nothing to say about my bets". A dog
with no tickets still has a rule. Now Ask runs it: right now (Fire now's machinery), earlier today (each game on the
board as it stood at its own decision time, labelled hindsight) and over a window of past days (the drill).

THE STANDARD GAME starts 23:10Z on 2026-10-20 (7:10 pm Eastern). Captures at 19:55 (open), 21:05 (lock for a
120-minute dog) and 22:20 (late). At the lock capture the moneyline is home -140 / away +120 on five books, so the
underdog is Boston at +120; the late capture (+150) must never be what a lock-time judgement sees.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_engine_v2 as v2
from src.hounds import user_spec
from src.hounds.interact import ask, ask_eval, common, drill, fire
from src.hounds.user_facts import FactBook
from tests._hounds_user_fixtures import (AWAY, BOOKS, EVENT, HOME, T_LOCK, board_rows, hound, standard_rows, utc)
from tests.test_hounds_interact_ask import CLAIMS, SUMMARY, TICKETS, context
from tests.test_hounds_interact_drill import INDEX, RESULTS
from tests.test_hounds_interact_drill import user_dog as drill_dog
from tests.test_hounds_interact_fire import dog_of, rows_for
from tests.test_hounds_interact_slate import nfl_rows

OWNER_QUESTION = "What bets would yopu have taken today pre market"
NO_TICKETS = "I have not recorded a ticket yet, so there is nothing to say about my bets"
NOW_BEFORE_LOCK = "2026-10-20T21:08:00Z"         # 5:08 pm Eastern; the lock is 5:10 pm
NOW_INSIDE_WINDOW = "2026-10-20T21:30:00Z"       # after the lock, before the start
NOW_AFTER_START = "2026-10-20T23:40:00Z"         # 7:40 pm Eastern, the game has started


def fixture_slate(rows):
    """A ``slate_for`` over fixture rows: the engine's own slate builder, with empty facts (nothing read from disk)."""
    def slate_for(date, with_props):
        return v2.build_slate(date, ["MLB", "NFL"], with_props=with_props, rows=list(rows), prop_rows=[],
                              facts=FactBook(), game_pk_index={})
    return slate_for


def v2_dog(**over):
    """A dog built from English rules (version 2): upgraded from the version-1 fixture, as the builder does."""
    h = hound("u-v2", **over)
    spec = user_spec.validate_spec({**user_spec.upgrade_v1(h["spec"]), "name": "Dog Days"})
    h.update({"spec": spec, "spec_hash": user_spec.spec_hash(spec), "owner_user_id": 7, "status": "running",
              "name": "Dog Days", "tagline": "", "root_id": "u-v2"})
    return common.Dog(id="u-v2", kind=common.KIND_USER, name="Dog Days", hound=h, owner_user_id=7, status="running",
                      root_id="u-v2")


class Tmp(unittest.TestCase):
    def setUp(self):
        fire.clear_cache()
        ask_eval.clear_cache()
        drill.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def ctx(self, dog, now, rows, *, tickets=(), **over):
        """An Ask context whose three evaluations run the REAL code over fixture boards."""
        slate_for = fixture_slate(rows)
        when = utc(now)
        if dog.kind == common.KIND_USER and not user_spec.is_v2(dog.spec):
            fire_fn = lambda: fire.fire_user(dog, now=when, rows_for=rows_for(rows), ledger=self.ledger)   # noqa: E731
        else:
            fire_fn = lambda: ask_eval.fire_v2(dog, now=when, slate_for=slate_for, ledger=self.ledger)     # noqa: E731
        base = dict(fire_fn=fire_fn, earlier_fn=lambda: ask_eval.earlier_user(dog, now=when, slate_for=slate_for),
                    tickets=list(tickets), manual=[], today=ask_eval.common.eastern_date(when), now=when,
                    summary=dict(SUMMARY, record={"bets": 0}, open_bets=0), tips=[], is_owner=True)
        base.update(over)
        return context(**base)

    def say(self, text, dog, now, rows, **over):
        return ask.answer(text, self.ctx(dog, now, rows, **over))


class TheOwnersQuestion(Tmp):
    def test_a_dog_with_no_tickets_runs_its_rules_for_the_exact_question_typed_on_a_phone(self):
        out = self.say(OWNER_QUESTION, dog_of(), NOW_AFTER_START, standard_rows())
        self.assertEqual(out["intent"], "picks_earlier_today")
        self.assertNotIn(NO_TICKETS, out["answer"])
        self.assertIn("Boston Red Sox to win", out["answer"])
        self.assertIn("+120", out["answer"])
        self.assertIn("Hindsight", out["answer"])

    def test_the_same_question_for_a_dog_built_from_english_rules(self):
        out = self.say(OWNER_QUESTION, v2_dog(), NOW_AFTER_START, standard_rows())
        self.assertEqual(out["intent"], "picks_earlier_today")
        self.assertIn("Boston Red Sox to win", out["answer"])
        self.assertNotIn(NO_TICKETS, out["answer"])

    def test_what_did_you_bet_today_with_no_tickets_runs_the_rules_instead_of_a_dead_end(self):
        out = self.say("what did you bet today", dog_of(), NOW_AFTER_START, standard_rows())
        self.assertEqual(out["intent"], "today")
        self.assertIn("I have not recorded a ticket yet", out["answer"])
        self.assertIn("here is what they would have taken today, in hindsight", out["answer"])
        self.assertIn("Boston Red Sox to win", out["answer"])
        self.assertEqual(out["cards"][0]["selection"], "Boston Red Sox to win")
        self.assertEqual(out["cards_at"], 1)             # after the one lead line, before the paper tail


class RightNow(Tmp):
    def test_a_version_1_dog_says_the_pick_the_price_the_game_the_time_and_why(self):
        out = self.say("What would you bet right now?", dog_of(), NOW_BEFORE_LOCK, standard_rows())
        self.assertEqual(out["intent"], "picks_now")
        a = out["answer"]
        self.assertLessEqual(len(out["lines"]), 2)             # one or two short lines in the hound's voice, then the card
        self.assertIn("Boston Red Sox to win at +120", a)
        self.assertNotIn("Rule: the underdog", a)              # the rule text is behind "How I checked it", never inline
        card = out["cards"][0]
        self.assertEqual((card["selection"], card["price"], card["game"], card["when"], card["state"]),
                         ("Boston Red Sox to win", 120, f"{AWAY} @ {HOME}", "Today 7:10 pm ET", "ahead"))
        self.assertEqual(card["reason"], "")
        self.assertTrue(any("Rule: the underdog" in line for line in out["details"]["lines"]))
        self.assertIn("21+", out["fine"])

    def test_a_version_2_dog_can_be_fired_at_all(self):
        """Before 2026-10-20 ``fire_user`` raised KeyError on a dog built from English rules."""
        dog = v2_dog()
        payload = ask_eval.fire_v2(dog, now=utc(NOW_BEFORE_LOCK), slate_for=fixture_slate(standard_rows()),
                                   ledger=self.ledger)
        self.assertEqual([p["selection"] for p in payload["picks"]], ["Boston Red Sox to win"])
        self.assertEqual(payload["picks"][0]["price_average"], 120)
        self.assertIn("Rule 1:", payload["picks"][0]["reason"])
        for key in ("headline", "slate", "closest_misses", "recorded", "notes", "games", "as_of", "paper_only"):
            self.assertIn(key, payload)
        out = self.say("what would you bet rn", dog, NOW_BEFORE_LOCK, standard_rows())
        self.assertIn("Boston Red Sox to win at +120", out["answer"])

    def test_the_fire_dispatcher_sends_a_version_2_dog_to_the_rule_set_engine(self):
        dog = v2_dog()
        with mock.patch.object(ask_eval, "default_slate", fixture_slate(standard_rows())):
            payload = fire.fire(dog, now=utc(NOW_BEFORE_LOCK), ledger=self.ledger)
        self.assertEqual(len(payload["picks"]), 1)

    def test_nothing_qualifying_names_the_closest_game_and_the_condition_that_failed_in_the_first_person(self):
        dog = dog_of(price_min=200, price_max=250)             # Boston is +120: outside the band
        out = self.say("what would you bet tonight", dog, NOW_BEFORE_LOCK, standard_rows())
        a = out["answer"]
        self.assertEqual(len(out["lines"]), 1)
        self.assertIn(f"Next game I'll check: {AWAY} @ {HOME}, Today 7:10 pm ET", a)     # names the next game, not a started one
        self.assertNotIn("Closest", a)                         # the near misses sit behind "How I checked it"
        why = " ".join(out["details"]["lines"])
        self.assertIn(f"Closest: {AWAY} @ {HOME} (Moneyline)", why)
        self.assertIn("shorter than my band of +200 to +250", why)
        self.assertNotIn("your band", why)
        self.assertEqual(out["cards"], [])
        self.assertIn("I looked at 1 game.", why)

    def test_a_version_2_dog_that_passes_names_the_failed_condition(self):
        dog = v2_dog(price_min=200, price_max=250)
        out = self.say("what would you bet right now", dog, NOW_BEFORE_LOCK, standard_rows())
        self.assertEqual(out["cards"], [])
        why = " ".join(out["details"]["lines"])
        self.assertIn(f"Closest: {AWAY} @ {HOME}", why)
        self.assertIn("outside the band my rule allows", why)

    def test_a_game_that_has_started_is_said_first_and_the_next_day_named(self):
        rows = standard_rows() + nfl_rows()
        dog = dog_of(sports=["MLB", "NFL"])
        out = self.say("what would you bet", dog, "2026-10-21T00:40:00Z", rows)
        self.assertNotIn(f"{AWAY} @ {HOME}", out["answer"])        # a game that has started is never filler
        self.assertNotIn("already started", out["answer"])
        self.assertIn("Thursday 8:15 pm ET", " ".join([out["answer"], out["cards"][0]["when"]]))
        self.assertEqual(out["cards"][0]["day"], "Thursday")

    def test_no_games_today_is_said_before_the_next_slate(self):
        out = self.say("any plays", dog_of(sports=["MLB", "NFL"]), "2026-10-20T14:00:00Z", nfl_rows())
        self.assertEqual([c["day"] for c in out["cards"]], ["Thursday"])     # nothing today: the fresh pick is the Thursday game
        self.assertNotIn("No games today", out["answer"])

    def test_a_dog_that_cannot_be_fired_still_answers_with_what_it_has(self):
        out = self.say("what would you bet right now", dog_of(), NOW_BEFORE_LOCK, standard_rows(), fire_fn=None,
                       tickets=TICKETS)
        self.assertIn("can't run my rule on demand", out["answer"])
        self.assertEqual(out["cards"], [])                       # never an answer made of a ticket it already placed
        for ticket in TICKETS:
            self.assertNotIn(ticket["selection"], out["answer"])

    def test_a_pick_at_minus_200_or_worse_is_never_offered(self):
        short = board_rows(T_LOCK, moneyline=[(b, -230, 190) for b in BOOKS])
        dog = dog_of(side_rule="favourite", price_min=-195, price_max=-110)
        out = self.say("what would you bet right now", dog, NOW_BEFORE_LOCK, short)
        self.assertEqual(out["cards"], [])
        self.assertIn("Past the -200 cap", " ".join(m["title"] for m in dog_fire_misses(self, dog, short)))
        self.assertNotIn("-230 ", out["answer"].split("Closest")[0])
        for text in ("what would you bet right now", "what would you have taken today pre market"):
            for the_dog in (dog, v2_dog(side_rule="favourite", price_min=-195, price_max=-110)):
                got = self.say(text, the_dog, NOW_AFTER_START, short)
                for card in got["cards"]:
                    self.assertGreater(card["price"], -200)


def dog_fire_misses(case, dog, rows):
    return fire.fire_user(dog, now=utc(NOW_BEFORE_LOCK), rows_for=rows_for(rows), ledger=case.ledger)["closest_misses"]


class EarlierToday(Tmp):
    def test_a_started_game_is_judged_on_the_board_at_its_own_decision_time_not_the_late_one(self):
        out = self.say("what would you have taken today", dog_of(), NOW_AFTER_START, standard_rows())
        self.assertEqual(out["cards"][0]["price"], 120)                  # the 21:05 board, never the 22:20 one (+150)
        self.assertNotIn("+150", out["answer"])
        self.assertIn("That game has started.", out["answer"])
        self.assertEqual(out["cards"][0]["state"], "started")
        self.assertTrue(out["hindsight"])
        self.assertIn("each game judged on the board as it stood at its own decision time", out["answer"])

    def test_a_game_still_ahead_is_judged_on_the_newest_board_and_says_it_can_change(self):
        out = self.say("what would you have taken today pre market", dog_of(), NOW_BEFORE_LOCK, standard_rows())
        self.assertEqual(out["cards"][0]["state"], "ahead")
        self.assertIn("placing time has not come yet", out["answer"])

    def test_nothing_would_have_qualified_names_the_closest_miss(self):
        dog = dog_of(price_min=200, price_max=250)
        out = self.say("what would you have taken today", dog, NOW_AFTER_START, standard_rows())
        self.assertIn("Nothing would have qualified.", out["answer"])
        self.assertIn(f"Closest: {AWAY} @ {HOME} (Moneyline)", out["answer"])
        self.assertIn("my band of +200 to +250", out["answer"])
        self.assertEqual(out["cards"], [])

    def test_a_version_2_dog_that_would_have_passed_says_which_condition_failed(self):
        out = self.say("what would you have taken today", v2_dog(price_min=200, price_max=250), NOW_AFTER_START,
                       standard_rows())
        self.assertIn("Nothing would have qualified.", out["answer"])
        self.assertIn("outside the band my rule allows", out["answer"])

    def test_the_daily_limit_cuts_the_list_and_says_how_many(self):
        second = board_rows("2026-10-20T23:50:00Z", event_id="evt0002", home="Houston Astros", away="Texas Rangers",
                            start="2026-10-21T02:10:00Z", moneyline=[(b, -130, 110) for b in BOOKS])
        rows = standard_rows() + second
        dog = dog_of(max_bets_per_day=1)
        out = self.say("what would you have taken today", dog, "2026-10-21T03:00:00Z", rows)
        self.assertEqual(len(out["cards"]), 1)
        self.assertIn("1 more would have qualified, but my daily limit stops me before it.", out["answer"])

    def test_a_day_with_no_game_says_so(self):
        out = self.say("what would you have taken today", dog_of(), "2026-10-25T15:00:00Z", standard_rows())
        self.assertIn("no games on today's board", out["answer"])

    def test_it_writes_nothing_and_leaves_the_clock_alone(self):
        before = set(os.listdir(self._tmp.name))
        self.say("what would you have taken today", dog_of(), NOW_AFTER_START, standard_rows())
        self.say("what would you have taken today", v2_dog(), NOW_AFTER_START, standard_rows())
        self.assertEqual(set(os.listdir(self._tmp.name)), before)

    def test_why_not_a_started_game_reads_its_decision_time_judgement(self):
        dog = dog_of(price_min=200, price_max=250)
        out = self.say("why didn't you bet the Red Sox", dog, NOW_AFTER_START, standard_rows(),
                       fire_fn=lambda: {"games": [], "picks": [], "closest_misses": []})
        self.assertIn("is on today's slate", out["answer"])
        self.assertIn("I would have passed.", out["answer"])
        self.assertIn("my band", out["answer"])


class HouseDogsEarlierToday(unittest.TestCase):
    def setUp(self):
        from src.hounds import pack as pack_mod, pack_run
        from src.hounds.learning import champions
        from tests.test_house_pack_hounds import START, basic_stores
        self.start, self.stores = START, basic_stores()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ledger = os.path.join(self._tmp.name, "hounds_house_v1.jsonl")
        for p in (mock.patch.object(pack_run, "ledger_path", lambda path=None: path or ledger),
                  mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs))):
            p.start()
            self.addCleanup(p.stop)
        h = pack_mod.BY_ID["chalk_chihuahua"]
        self.dog = common.Dog(id=h.id, kind=common.KIND_HOUSE, name=h.name, tagline=h.tagline, house=h, root_id=h.id)

    def test_a_pack_dog_replays_todays_started_games_at_their_placing_time(self):
        payload = ask_eval.earlier_house(self.dog, now=self.start + timedelta(minutes=5), stores=self.stores)
        self.assertEqual(payload["picks"][0]["selection"], "Boston Red Sox ML")
        self.assertEqual(payload["picks"][0]["price_average"], -130)
        out = ask.answer("what would you have taken today", context(
            kind="house", name="Chalk Chihuahua", earlier_fn=lambda: payload, tickets=[], now=self.start))
        self.assertIn("Boston Red Sox ML at -130", out["answer"])
        self.assertTrue(out["hindsight"])

    def test_before_any_game_has_started_it_says_so_and_points_at_right_now(self):
        from src.hounds.interact import common as c
        payload = ask_eval.earlier_house(self.dog, now=self.start - timedelta(minutes=90), stores=self.stores)
        self.assertEqual(payload["picks"], [])
        out = ask.answer("what would you have taken today", context(
            kind="house", name="Chalk Chihuahua", earlier_fn=lambda: payload, tickets=[], now=self.start))
        self.assertIn("None of today's games have started yet", out["answer"])
        self.assertIsNotNone(c)


class TheReplay(Tmp):
    """The drill, summarised: W-L, dollars on the $1,000 paper bankroll, return, best and worst pick."""
    NOW = "2026-10-22T12:00:00Z"                 # the drill's 7 days cover 2026-10-15 .. 2026-10-21

    def backtest_fn(self, dog, now=None, **over):
        inject = dict(rows_by_date={"2026-10-20": standard_rows()}, mlb_results=RESULTS, nfl_results=lambda d: {},
                      game_pk_index=INDEX)
        inject.update(over)
        return lambda days: ask_eval.backtest(dog, days, signed_in=True, now=utc(now or self.NOW), **inject)

    def replay(self, text, dog=None, today="2026-10-22", **over):
        dog = dog or drill_dog()
        return ask.answer(text, context(backtest_fn=self.backtest_fn(dog, **over), today=today, now=utc(self.NOW)))

    def test_the_week_is_summarised_in_dollars_and_a_return(self):
        out = self.replay("what would you have done this week")
        self.assertEqual(out["intent"], "backtest_window")
        a = out["answer"]
        self.assertIn("1 graded bet: 1-0, up $12.00 on a $1,000 paper bankroll, a +1.2% return", a)
        self.assertIn("one unit is $10 a bet, flat", a)
        self.assertIn("Best pick: Boston Red Sox to win", a)
        self.assertIn("not counted", a)
        self.assertIn("a small sample", a)
        self.assertNotIn("Worst pick", a)

    def test_the_replay_speaks_in_the_askers_unit_size(self):
        # 2026-10-21 (unit-size lens): the same bet at a $50 unit is $60.00 on a $5,000 paper bankroll, and the return is the same 1.2%
        from src.hounds import unit_size
        ctx = context(backtest_fn=self.backtest_fn(drill_dog()), today="2026-10-22", now=utc(self.NOW),
                      sizing=unit_size.validate({"mode": "fixed", "unit_usd": 50}))
        a = ask.answer("what would you have done this week", ctx)["answer"]
        self.assertIn("1 graded bet: 1-0, up $60.00 on a $5,000 paper bankroll, a +1.2% return (one unit is $50 a bet, flat).", a)
        self.assertNotIn("$10", a)

    def test_a_percent_of_bankroll_asker_gets_the_compounded_dollars(self):
        from src.hounds import unit_size
        ctx = context(backtest_fn=self.backtest_fn(drill_dog()), today="2026-10-22", now=utc(self.NOW),
                      sizing=unit_size.validate({"mode": "percent", "pct": 2, "start_usd": 5000}))
        a = ask.answer("what would you have done this week", ctx)["answer"]
        self.assertIn("up $120.00 on a $5,000 paper bankroll, a +2.4% return at your sizing "
                      "(one unit is 2% of the balance when the bet is placed, so it compounds).", a)

    def test_the_glossary_names_the_askers_unit(self):
        from src.hounds import unit_size
        fixed = ask.answer("what is a unit", context(sizing=unit_size.validate({"mode": "fixed", "unit_usd": 50})))["answer"]
        self.assertIn("one unit is $50, 1% of the $5,000 start", fixed)
        pct = ask.answer("what is a unit", context(sizing=unit_size.validate({"mode": "percent", "pct": 1.5, "start_usd": 4000})))["answer"]
        self.assertIn("one unit is 1.5% of the balance when the bet is placed", pct)

    def test_a_loss_is_the_worst_pick_and_the_dollars_go_down(self):
        out = self.replay("what would you have done in the last 7 days",
                          mlb_results={"900001": dict(RESULTS["900001"], away_score="1", home_score="3")})
        self.assertIn("0-1, down $10.00", out["answer"])
        self.assertIn("-1.0% return", out["answer"])
        self.assertIn("Worst pick: Boston Red Sox to win", out["answer"])

    def test_a_named_day_is_filtered_from_the_window(self):
        out = self.replay("what would you have taken yesterday", today="2026-10-21", now="2026-10-21T12:00:00Z")
        self.assertIn("Replaying my rules over yesterday", out["answer"])
        self.assertIn("1-0", out["answer"])
        out = self.replay("what would you have done last weekend", today="2026-10-21", now="2026-10-21T12:00:00Z")
        self.assertIn("would not have placed a bet in that window", out["answer"])

    def test_a_window_longer_than_the_drill_allows_is_clipped_and_says_so(self):
        out = self.replay("what would you have done in the last 90 days")
        self.assertIn("at most 30 days", out["answer"])

    def test_a_busy_drill_says_so_with_the_seconds_to_wait(self):
        slot = drill._drill_slot
        self.assertTrue(slot.acquire(blocking=False))
        try:
            out = self.replay("what would you have done this week")
        finally:
            slot.release()
        self.assertIn("Another replay is running, so I cannot start mine yet. Try again in 30 seconds.", out["answer"])
        self.assertEqual(out["busy"], {"kind": "drill", "retry_after": 30})

    def test_a_signed_out_visitor_is_asked_to_sign_in_unless_the_replay_is_already_remembered(self):
        dog = drill_dog()
        fn = lambda days: ask_eval.backtest(dog, days, signed_in=False, now=utc(self.NOW))     # noqa: E731
        out = ask.answer("what would you have done this week", context(backtest_fn=fn, today="2026-10-22"))
        self.assertIn("for signed-in visitors", out["answer"])
        self.assertEqual(out["busy"]["kind"], "signin")
        key = ("user", dog.id, user_spec.spec_hash(dog.spec), 7, common.eastern_date(utc(self.NOW)))
        remembered = drill.drill(days=7, dog=dog, now=utc(self.NOW), rows_by_date={"2026-10-20": standard_rows()},
                                 mlb_results=RESULTS, nfl_results=lambda d: {}, game_pk_index=INDEX)
        with mock.patch.dict(drill._cache, {key: (time.monotonic(), remembered)}):
            out = ask.answer("what would you have done this week", context(backtest_fn=fn, today="2026-10-22"))
        self.assertIn("1-0", out["answer"])

    def test_a_refused_allowance_is_said_with_its_retry_seconds(self):
        def refuse(_days):
            raise ask_eval.Busy("rate", 12)
        out = ask.answer("what would you have done this week", context(backtest_fn=refuse))
        self.assertIn("Try me again in 12 seconds.", out["answer"])

    def test_the_replay_writes_nothing_to_the_real_ledger(self):
        self.replay("what would you have done this week")
        self.assertFalse(os.path.exists(self.ledger))


class AQuestionNobodyRecognised(unittest.TestCase):
    GIBBERISH = ["banana smoothie recipe", "asdf", "qwerty uiop", "???", "lorem ipsum dolor sit amet", "42",
                 "how tall is the eiffel tower", "sing me a song", "tell me a joke", "xyzzy", "do the thing",
                 "what is the capital of france", "zzzz", "purple monkey dishwasher", "blah blah blah"]

    def test_it_is_never_a_dead_end_it_gives_the_closest_thing_and_the_menu(self):
        for text in self.GIBBERISH:
            out = ask.answer(text, context())
            self.assertFalse(out["matched"], text)
            a = out["answer"]
            self.assertIn("closest thing I have", a, text)
            self.assertIn("what I would have taken earlier today", a, text)
            self.assertIn("what I would bet right now", a, text)
            self.assertGreater(len(out["lines"]), 3, text)

    def test_a_half_understood_picks_question_offers_to_run_the_rules_by_name(self):
        out = ask.answer("what about the games", context())
        self.assertFalse(out["matched"])
        self.assertIn("Ask it like this", out["answer"]) if "Ask it like this" in out["answer"] else None
        self.assertIn("what I would bet right now", out["answer"])

    def test_it_answers_in_the_first_person_with_no_claim(self):
        for text in self.GIBBERISH:
            self.assertIsNone(CLAIMS.search(ask.answer(text, context())["answer"]), text)


class ABettingTerm(unittest.TestCase):
    def test_the_glossary_answers_a_term_in_plain_words(self):
        for text, needle in (("what is a spread", "margin"), ("whats a run line", "1.5 runs"),
                             ("what does over under mean", "combined score"), ("what is a prop bet", "one player"),
                             ("what are units", "$10"), ("what is a bankroll", "$1,000"),
                             ("explain a parlay", "single bet"), ("what does push mean", "tie"),
                             ("what is a moneyline", "who wins"), ("what is clv", "price when the game started")):
            out = ask.answer(text, context())
            self.assertEqual(out["intent"], "explain_market", text)
            self.assertIn(needle, out["answer"], text)
            self.assertIsNone(CLAIMS.search(out["answer"]), text)

    def test_the_cap_is_stated_wherever_a_favourite_is_explained(self):
        self.assertIn("-200 or worse", ask.answer("what is a favourite", context())["answer"])


class EveryAnswerIsPaperOnlyWithNoClaim(Tmp):
    QUESTIONS = ["what would you bet right now", OWNER_QUESTION, "what would you have done this week", "help",
                 "what is a spread", "how are you doing", "who are you", "asdf"]

    def test_no_answer_claims_an_edge_shouts_or_promises(self):
        for dog in (dog_of(), v2_dog()):
            for text in self.QUESTIONS:
                backtest = self.backtest(dog)
                out = ask.answer(text, self.ctx(dog, NOW_AFTER_START, standard_rows(), backtest_fn=backtest))
                self.assertTrue(out["paper_only"])
                self.assertIsNone(CLAIMS.search(out["answer"]), (text, out["answer"]))
                for card in out["cards"]:
                    self.assertIsNone(CLAIMS.search(card["reason"]), card["reason"])
                self.assertIsNone(re.search(r"\s-(2\d\d|[3-9]\d\d)\b(?!.*cap)", " ".join(c["price_text"] for c in out["cards"])))

    def backtest(self, dog):
        return lambda days: ask_eval.backtest(dog, days, signed_in=True, now=utc("2026-10-22T12:00:00Z"),
                                              rows_by_date={"2026-10-20": standard_rows()}, mlb_results=RESULTS,
                                              nfl_results=lambda d: {}, game_pk_index=INDEX)


class TheEvaluationsAreGated(unittest.TestCase):
    """The route-level allowances (api/hounds_interact.py) are exercised in test_hounds_interact_api; here, the pure
    seam: an evaluation that raises ``Busy`` becomes a sentence with the seconds, never a 500 and never a retry."""

    def test_a_rate_refusal_on_the_boards_is_a_sentence(self):
        def refuse():
            raise ask_eval.Busy("rate", 9)
        for text in ("what would you bet right now", "what would you have taken today"):
            out = ask.answer(text, context(fire_fn=refuse, earlier_fn=refuse))
            self.assertIn("Try me again in 9 seconds.", out["answer"], text)
            self.assertEqual(out["busy"]["retry_after"], 9)

    def test_one_slate_read_serves_twenty_simultaneous_questions(self):
        calls = []
        real = v2.build_slate

        def slow(*a, **k):
            calls.append(1)
            time.sleep(0.05)
            k.update(rows=standard_rows(), prop_rows=[], facts=FactBook(), game_pk_index={})
            return real(*a, **k)
        results = []
        with mock.patch.object(ask_eval.V2, "build_slate", slow):
            ask_eval.clear_cache()
            threads = [threading.Thread(target=lambda: results.append(ask_eval.default_slate("2026-10-20", False)))
                       for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 20)
        ask_eval.clear_cache()


if __name__ == "__main__":
    unittest.main()
