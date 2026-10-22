"""The slate in the viewer's terms (src/hounds/interact/fire.py ``slate_view``, ``day_label``), on a fixed clock.

THE STORY (owner, 2026-10-20 00:50Z). A member dog asked "what would you bet" while tonight's games (MLB 00:10Z,
Monday night football 00:15Z) had already started. The list began with a Thursday game, and the owner read that
as "it is not looking at today's games". The answer now says so first: which of today's games have started, and
which day the next ones are. Every case below pins one sentence, with a clock that never moves.

Eastern dates throughout (the sport's own clock): 2026-10-20 is a Tuesday, 2026-10-22 a Thursday.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds.interact import common, fire
from tests._hounds_user_fixtures import AWAY, HOME, START, board_rows, hound, standard_rows, utc
from tests.test_hounds_interact_fire import dog_of, rows_for

NFL_START = "2026-10-23T00:15:00Z"           # Thursday 8:15 pm Eastern
NFL_BOOKS = ("book_a", "book_b", "book_c", "book_d", "book_e")


def nfl_rows():
    return board_rows("2026-10-20T12:00:00Z", event_id="nfl0001", home="Chicago Bears", away="New England Patriots",
                      start=NFL_START, sport="NFL", moneyline=[(b, -150, 130) for b in NFL_BOOKS])


def late_rows():
    """A second MLB game the same Eastern evening: 2026-10-21T02:10Z is 10:10 pm on Tuesday the 20th."""
    return board_rows("2026-10-21T00:20:00Z", event_id="evt0002", home="Houston Astros", away="Texas Rangers",
                      start="2026-10-21T02:10:00Z", moneyline=[(b, -130, 110) for b in NFL_BOOKS])


def wednesday_rows():
    return board_rows("2026-10-21T15:00:00Z", event_id="evt0003", home="Cleveland Guardians", away="Tampa Bay Rays",
                      start="2026-10-21T23:10:00Z", moneyline=[(b, -130, 110) for b in NFL_BOOKS])


class Tmp(unittest.TestCase):
    def setUp(self):
        fire.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def fire(self, now, rows, **dog_over):
        dog = dog_of(**dog_over)
        return fire.fire_user(dog, now=utc(now), rows_for=rows_for(rows), ledger=self.ledger)


class DayLabels(unittest.TestCase):
    NOW = utc("2026-10-20T15:00:00Z")          # Tuesday 11 am Eastern

    def test_today_tomorrow_a_weekday_then_a_date(self):
        self.assertEqual(fire.day_label("2026-10-20", self.NOW), "Today")
        self.assertEqual(fire.day_label("2026-10-21", self.NOW), "Tomorrow")
        self.assertEqual(fire.day_label("2026-10-22", self.NOW), "Thursday")
        self.assertEqual(fire.day_label("2026-10-26", self.NOW), "Monday")
        self.assertEqual(fire.day_label("2026-10-27", self.NOW), "Oct 27")

    def test_the_label_follows_the_eastern_date_not_the_utc_date(self):
        late = utc("2026-10-21T01:30:00Z")      # still Tuesday evening in New York
        self.assertEqual(fire.day_label("2026-10-20", late), "Today")
        self.assertEqual(fire.day_of(utc("2026-10-21T00:10:00Z")), "2026-10-20")

    def test_times_are_eastern_with_the_zone_named(self):
        self.assertEqual(fire.clock_et(utc("2026-10-21T00:10:00Z")), "8:10 pm ET")
        self.assertEqual(fire.clock_et(utc("2026-10-20T16:05:00Z")), "12:05 pm ET")
        self.assertEqual(fire.clock_et(utc("2026-10-20T04:00:00Z")), "12:00 am ET")


class TonightsGamesStarted(Tmp):
    """Tuesday 8:40 pm Eastern. The standard game started at 7:10 pm; the Patriots play Thursday."""
    NOW = "2026-10-21T00:40:00Z"

    def test_it_says_tonights_games_started_then_names_the_next_day(self):
        out = self.fire(self.NOW, standard_rows() + nfl_rows(), sports=["MLB", "NFL"])
        slate = out["slate"]
        self.assertEqual(slate["today_state"], "started")
        # 2026-10-22: counts, never a game's name in the sentence (the games sit in ``started`` / ``groups``, folded on the page)
        self.assertEqual(slate["line"], "Tonight's games already started (1). Next games I can bet: Thursday.")
        self.assertEqual(slate["counts"], {"total": 1, "started": 1, "later": 0, "checked_now": 0})
        self.assertEqual(slate["counts_line"], "1 game today \u00b7 1 started")
        self.assertEqual(slate["started"][0]["start_utc"], START)
        self.assertEqual(slate["started"][0]["game"], f"{AWAY} @ {HOME}")
        self.assertEqual([g["key"] for g in slate["groups"]], ["started"])
        self.assertEqual(slate["next_day_label"], "Thursday")
        self.assertEqual([d["label"] for d in slate["days"]], ["Thursday"])

    def test_the_started_game_is_never_a_pick_and_the_thursday_pick_is_labelled_thursday(self):
        out = self.fire(self.NOW, standard_rows() + nfl_rows(), sports=["MLB", "NFL"])
        self.assertEqual([p["game"] for p in out["picks"]], ["New England Patriots @ Chicago Bears"])
        self.assertEqual((out["picks"][0]["day"], out["picks"][0]["day_label"]), ("2026-10-22", "Thursday"))
        self.assertEqual(out["games_considered"], 1)

    def test_with_no_later_game_on_file_it_says_so(self):
        out = self.fire(self.NOW, standard_rows())
        self.assertEqual(out["slate"]["line"], "Tonight's games already started (1). No later games are on the stored boards yet.")
        self.assertEqual(out["picks"], [])

    def test_in_the_morning_it_is_todays_not_tonights(self):
        # the same game, read at 10:30 am the NEXT Eastern day it began on, would not count; so read a game that
        # began at 1:05 pm Eastern with the clock at 3 pm
        rows = board_rows("2026-10-20T16:00:00Z", event_id="evt0009", start="2026-10-20T17:05:00Z",
                          moneyline=[(b, -130, 110) for b in NFL_BOOKS])
        out = self.fire("2026-10-20T19:00:00Z", rows)
        self.assertTrue(out["slate"]["line"].startswith("Today's games already started (1)"), out["slate"]["line"])
        self.assertEqual(out["slate"]["started"][0]["start_et"], "1:05 pm ET")

    def test_a_game_that_started_yesterday_is_not_named_as_todays(self):
        out = self.fire("2026-10-21T14:00:00Z", standard_rows())      # Wednesday 10 am; the game began Tuesday 7:10 pm
        self.assertEqual(out["slate"]["started"], [])


class NothingOnTheBoardToday(Tmp):
    NOW = "2026-10-21T14:00:00Z"                 # Wednesday 10 am Eastern

    def test_no_games_today_names_the_next_slate_day(self):
        out = self.fire("2026-10-20T14:00:00Z", nfl_rows(), sports=["MLB", "NFL"])      # Tuesday 10 am
        self.assertEqual(out["slate"]["today_state"], "none")
        # the next game is said once, by ``next_game`` (and the Unleash day's "Next game it checks"), not again in the sentence
        self.assertEqual(out["slate"]["line"], "No games today. Next slate: Thursday.")
        self.assertEqual(out["slate"]["next_game"]["game"], "New England Patriots @ Chicago Bears")
        self.assertEqual(out["slate"]["next_game"]["text"], "New England Patriots @ Chicago Bears (8:15 pm ET)")

    def test_no_games_at_all_says_that_too(self):
        out = self.fire(self.NOW, [])
        self.assertEqual(out["slate"]["today_state"], "none")
        self.assertEqual(out["slate"]["line"], "No games today, and none are on the stored boards yet.")
        self.assertIn("No upcoming game", out["headline"])

    def test_tomorrow_is_called_tomorrow(self):
        out = self.fire("2026-10-20T14:00:00Z", wednesday_rows())     # Tuesday 10 am; the game is Wednesday evening
        self.assertEqual(out["slate"]["line"], "No games today. Next slate: Tomorrow.")
        self.assertEqual(out["slate"]["next_game"]["text"], "Tampa Bay Rays @ Cleveland Guardians (7:10 pm ET)")
        self.assertEqual([d["label"] for d in out["slate"]["days"]], ["Tomorrow"])


class GamesStillAheadToday(Tmp):
    def test_an_open_slate_needs_no_warning_and_its_picks_say_today(self):
        out = self.fire("2026-10-20T21:08:00Z", standard_rows())      # 5:08 pm Eastern, lock at 5:10 pm
        self.assertEqual(out["slate"]["today_state"], "open")
        self.assertEqual(out["slate"]["line"], "")
        self.assertEqual(out["picks"][0]["day_label"], "Today")

    def test_some_started_and_some_still_ahead_says_both(self):
        out = self.fire("2026-10-21T00:40:00Z", standard_rows() + late_rows())
        self.assertEqual(out["slate"]["today_state"], "open")
        self.assertEqual(out["slate"]["line"], "1 started today. 1 game still ahead today. 1 inside my placing window now.")
        self.assertEqual(out["slate"]["counts"], {"total": 2, "started": 1, "later": 0, "checked_now": 1})
        self.assertEqual(out["slate"]["counts_line"], "2 games today \u00b7 1 started \u00b7 1 checked now")
        self.assertEqual([g["key"] for g in out["slate"]["groups"]], ["started", "checked_now"])

    def test_a_game_inside_the_placing_window_is_named(self):
        out = self.fire("2026-10-20T21:30:00Z", standard_rows())      # lock was 21:10, the game starts 23:10
        self.assertEqual(out["slate"]["today_state"], "open")
        self.assertEqual(out["slate"]["line"], "1 inside my placing window now.")
        self.assertEqual(out["slate"]["in_window"][0]["game"], f"{AWAY} @ {HOME}")


class TheDayIsCountsNotAPrintout(unittest.TestCase):
    """Owner, 2026-10-22: the day view dumped every game by name ("Already started today: Belinda Bencic @ ... (11:20 PM PDT), ..." and a
    30-game "Inside my placing window now" list) and "looked sloppy". The sentence is counts; the games are data for a folded list."""
    NOW = utc("2026-10-21T00:40:00Z")           # Tuesday 8:40 pm Eastern

    def slate(self, n_started=12, n_window=14, n_later=34):
        started = [(f"Away{i} @ Home{i}", self.NOW - timedelta(minutes=30 + i)) for i in range(n_started)]
        upcoming = [(f"WinA{i} @ WinH{i}", self.NOW + timedelta(minutes=20 + i), self.NOW - timedelta(minutes=5)) for i in range(n_window)]
        upcoming += [(f"LateA{i} @ LateH{i}", self.NOW + timedelta(minutes=130 + i), self.NOW + timedelta(minutes=10 + i)) for i in range(n_later)]
        return fire.slate_view(self.NOW, started, upcoming)

    def test_no_sentence_names_a_game(self):
        view = self.slate()
        for text in (view["line"], view["counts_line"]):
            self.assertNotRegex(text, r"@|Away|Home|WinA|LateA")

    def test_the_counts_add_up_and_the_line_is_one_tidy_block(self):
        view = self.slate()
        c = view["counts"]
        self.assertEqual(c, {"total": 60, "started": 12, "later": 34, "checked_now": 14})
        self.assertEqual(c["started"] + c["later"] + c["checked_now"], c["total"])
        self.assertEqual(view["counts_line"], "60 games today \u00b7 12 started \u00b7 34 later \u00b7 14 checked now")

    def test_the_groups_hold_every_game_once_and_are_capped(self):
        view = self.slate(n_started=50, n_window=3, n_later=2)
        groups = {g["key"]: g for g in view["groups"]}
        self.assertEqual(len(groups["started"]["games"]), fire.MAX_LISTED)
        self.assertEqual(groups["started"]["more"], 50 - fire.MAX_LISTED)
        self.assertEqual((len(groups["checked_now"]["games"]), groups["checked_now"]["more"]), (3, 0))
        names = [g["game"] for grp in view["groups"] for g in grp["games"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(view["counts"]["total"], 55)

    def test_a_zero_part_is_left_out_and_an_empty_day_has_no_block(self):
        self.assertEqual(fire.counts_line({"total": 3, "started": 3, "later": 0, "checked_now": 0}), "3 games today \u00b7 3 started")
        self.assertEqual(fire.counts_line({"total": 1, "started": 0, "later": 1, "checked_now": 0}), "1 game today \u00b7 1 later")
        self.assertEqual(fire.counts_line({"total": 0, "started": 0, "later": 0, "checked_now": 0}), "")


class TheViewIsPureAndKeepsTheOldFields(unittest.TestCase):
    def test_slate_view_with_nothing_is_a_calm_empty_view(self):
        view = fire.slate_view(utc("2026-10-20T15:00:00Z"), [], [])
        self.assertEqual((view["today_state"], view["started"], view["days"]), ("none", [], []))
        self.assertTrue(view["line"].startswith("No games today"))

    def test_payload_still_carries_every_field_the_page_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "l.jsonl")):
                fire.clear_cache()
                out = fire.fire_user(dog_of(), now=utc("2026-10-20T19:00:00Z"), rows_for=rows_for(standard_rows()),
                                     ledger=os.path.join(tmp, "l.jsonl"))
        for key in ("picks", "closest_misses", "recorded", "headline", "notes", "preview_note", "slate", "as_of"):
            self.assertIn(key, out)
        for key in ("counts", "counts_line", "groups"):
            self.assertIn(key, out["slate"])


class HouseDogsSayItToo(unittest.TestCase):
    """The pack path builds the same view from its own events."""

    def setUp(self):
        from src.hounds import pack as pack_mod, pack_run
        from src.hounds.learning import champions
        from tests.test_house_pack_hounds import START, basic_stores
        self.start = START
        self.stores = basic_stores()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ledger = os.path.join(self._tmp.name, "hounds_house_v1.jsonl")
        for p in (mock.patch.object(pack_run, "ledger_path", lambda path=None: path or ledger),
                  mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs))):
            p.start()
            self.addCleanup(p.stop)
        h = pack_mod.BY_ID["chalk_chihuahua"]
        self.dog = common.Dog(id=h.id, kind=common.KIND_HOUSE, name=h.name, tagline=h.tagline, house=h, root_id=h.id)

    def test_a_house_dog_names_the_game_that_already_started(self):
        from datetime import timedelta
        out = fire.fire_house(self.dog, now=self.start + timedelta(minutes=5), stores=self.stores, recorded=set())
        slate = out["slate"]
        self.assertEqual(slate["today_state"], "started")
        self.assertEqual(len(slate["started"]), 1)
        self.assertIn("already started (1)", slate["line"])
        self.assertEqual(slate["counts"]["started"], 1)

    def test_a_house_pick_before_the_start_carries_its_day(self):
        from datetime import timedelta
        out = fire.fire_house(self.dog, now=self.start - timedelta(minutes=90), stores=self.stores, recorded=set())
        self.assertEqual(out["picks"][0]["day_label"], "Today")
        self.assertEqual(out["slate"]["today_state"], "open")


if __name__ == "__main__":
    unittest.main()
