"""src/situation/ufc.py: `situation_for_bout`, checked on the UFC data layer's own synthetic
world (tests/test_datasvc_ufc_features.py): five fighters, twelve completed bouts and a
scheduled main event, 9101, Alex Archer (a, 101) against Ben Brawler (b, 102), five rounds,
2026-10-10T23:00Z, Welterweight.

Hand-checked from that world's bout table:

  Archer (101), five fights before the bout, oldest first: 9001 W KO, 9003 L SUB, 9006 W DEC,
  9009 L DEC (to Brawler), 9011 W DEC. Last fought 2026-06-13T22:00Z: 119 days before the bout.
  Brawler (102): 9002 W DEC, 9004 W KO, 9008 W SUB, 9009 W DEC (over Archer), 9012 L SUB.
  Last fought 2026-08-08T22:00Z: 63 days before the bout.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from src.analyst import critic
from src.datasvc.ufc import matchup as mu
from src.situation import record as rec
from src.situation import ufc
from tests import ufc_analyst_fixtures as UF


def by_key(record):
    return {(f["family"], f["name"], f["side"]): f for f in record["factors"]}


def gaps_of(record):
    return {(g["family"], g["name"], g["side"]): g["reason"] for g in record["missing"]}


class Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = UF.make_store(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class TheHandCheckedMainEvent(Case):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = ufc.situation_for_bout(cls.store, "9101", strict=True)
        cls.f = by_key(cls.r)

    def v(self, family, name, side):
        return self.f[(family, name, side)]

    def test_it_is_sound_and_drawn_at_the_bouts_scheduled_start(self):
        self.assertEqual(rec.problems(self.r), [])
        self.assertEqual(self.r["sport"], "ufc")
        self.assertEqual(self.r["as_of"], "2026-10-10T23:00:00Z")
        self.assertEqual(self.r["subject"]["fighter_a"], "Alex Archer")
        self.assertEqual(self.r["coverage"], {"data_starts": "2025-01-18", "fights_a": 5, "fights_b": 5})

    def test_days_since_the_last_fight(self):
        a = self.v("rest_and_rhythm", "days_since_last_fight", "a")
        b = self.v("rest_and_rhythm", "days_since_last_fight", "b")
        self.assertEqual((a["value"], a["as_of"]), (119, "2026-06-13T22:00:00Z"))
        self.assertEqual(a["sentence"], "Alex Archer last fought 119 days before this bout (2026-06-13): "
                                        "a win on the scorecards against Dan Silva.")
        self.assertEqual((b["value"], b["detail"]["bucket"]), (63, "normal"))
        self.assertEqual(b["sentence"], "Ben Brawler last fought 63 days before this bout (2026-08-08): "
                                        "a loss by submission against Cal Clinch.")

    def test_fights_in_the_last_365_days(self):
        # Archer: 2026-03-14 and 2026-06-13; Brawler: 2026-01-24, 2026-03-14 and 2026-08-08
        self.assertEqual(self.v("rest_and_rhythm", "fights_last_365_days", "a")["value"], 2)
        self.assertEqual(self.v("rest_and_rhythm", "fights_last_365_days", "b")["value"], 3)
        self.assertIs(self.v("rest_and_rhythm", "fights_last_365_days", "a")["detail"]["window_complete"], True)

    def test_the_streak(self):
        a, b = self.v("form", "streak", "a"), self.v("form", "streak", "b")
        self.assertEqual((a["value"], a["detail"]["type"], a["sentence"]),
                         (1, "win", "Alex Archer won the last UFC fight on file."))
        self.assertEqual((b["value"], b["detail"]["type"], b["sentence"]),
                         (1, "loss", "Ben Brawler lost the last UFC fight on file."))

    def test_recent_finishes_over_the_last_five(self):
        a, b = self.v("form", "recent_finishes", "a"), self.v("form", "recent_finishes", "b")
        self.assertEqual(a["detail"], {"finishing_wins": 1, "decision_wins": 2, "finishing_losses": 1})
        self.assertEqual(b["detail"], {"finishing_wins": 2, "decision_wins": 2, "finishing_losses": 1})
        self.assertEqual(b["sentence"], "In the last 5 fights on file, Ben Brawler has 2 finishing wins, "
                                        "2 decision wins and has been finished 1 time.")

    def test_opponent_quality_needs_enough_opponents_with_a_record(self):
        # Brawler's last three opponents had won 5/9 of their earlier fights on average, the one before 0
        b = self.v("form", "opponent_quality_trend", "b")
        self.assertEqual(b["sample"], {"recent_opponents": 3, "earlier_opponents": 1})
        self.assertAlmostEqual(b["detail"]["recent_mean"], 0.5556, places=4)
        self.assertEqual(b["detail"]["earlier_mean"], 0.0)
        self.assertEqual(b["value"], 0.5556)
        self.assertIn(("form", "opponent_quality_trend", "a"), gaps_of(self.r))

    def test_the_card_slot(self):
        c = self.v("stakes", "card_position", "game")
        self.assertEqual(c["value"], 1)
        self.assertEqual(c["sentence"], "The main event, main card, scheduled for 5 rounds.")
        self.assertEqual(c["detail"], {"main_event": True, "card_segment": "main", "scheduled_rounds": 5})

    def test_a_schedule_that_does_not_say_title_is_missing_not_false(self):
        self.assertNotIn(("stakes", "title_bout", "game"), self.f)
        self.assertIn(("stakes", "title_bout", "game"), gaps_of(self.r))

    def test_the_previous_meeting_is_written_from_the_data_not_from_the_bouts_orientation(self):
        m = self.v("head_to_head", "previous_meeting", "game")
        self.assertEqual(m["value"], 1)
        self.assertEqual(m["detail"]["meetings"], [{"date": "2026-03-14", "winner": "Ben Brawler",
                                                    "method": "DEC_UNANIMOUS", "round": 5}])
        self.assertEqual(m["sentence"], "Alex Archer and Ben Brawler have fought once before, on 2026-03-14: "
                                        "Ben Brawler won by unanimous decision.")

    def test_opponents_they_share(self):
        c = self.v("head_to_head", "common_opponents", "game")
        self.assertEqual((c["value"], c["sample"]), (3, {"opponents_a": 4, "opponents_b": 4}))

    def test_same_weight_class_both_sides(self):
        for side in ("a", "b"):
            w = self.v("availability", "weight_class_change", side)
            self.assertEqual((w["value"], w["detail"]), ("same", {"from": "Welterweight", "to": "Welterweight"}))

    def test_short_notice_and_missed_weight_are_missing_not_guessed(self):
        reason = gaps_of(self.r)[("availability", "short_notice_and_missed_weight", "game")]
        self.assertIn("not in the data", reason)
        self.assertIn(("stakes", "rankings", "game"), gaps_of(self.r))

    def test_the_page_block(self):
        shown = [(self.r["factors"][i]["name"], self.r["factors"][i]["side"]) for i in self.r["display"]]
        self.assertEqual(shown[:2], [("card_position", "game"), ("days_since_last_fight", "a")])
        self.assertIn(("previous_meeting", "game"), shown)


class ALeakInTheWorld(Case):
    """The bout's own result, a later bout and a bout with no result never count."""

    def test_finishing_the_bout_and_adding_later_bouts_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            baseline = ufc.situation_for_bout(store, "9101", strict=True)
            UF.finish_the_bout(store)                      # the bout's own result, an absurd KO
            later = dict(store.bout_by_id()["9013"], bout_id="9500", date_utc="2026-12-12T22:00Z",
                         status="final", winner_id="102", result_method="KO_TKO", end_round=1,
                         end_time_s=10.0, fight_time_s=10.0, event_id="7500")
            store.upsert("bouts", [later])
            self.assertEqual(ufc.situation_for_bout(store, "9101", strict=True), baseline)

    def test_a_bout_that_started_before_with_no_result_is_not_a_fight(self):
        # 9013 was cancelled before 9101 and is not in anyone's record
        r = ufc.situation_for_bout(self.store, "9101", strict=True)
        self.assertEqual(r["coverage"]["fights_a"], 5)

    def test_every_factor_is_stamped_before_the_start(self):
        r = ufc.situation_for_bout(self.store, "9101", strict=True)
        for f in r["factors"]:
            self.assertLess(f["as_of"], r["as_of"], f"{f['family']}.{f['name']}")

    def test_an_earlier_bout_sees_only_what_came_before_it(self):
        # 9009 (2026-03-14, Archer against Brawler): Archer's last fight before it was 9006
        r = ufc.situation_for_bout(self.store, "9009", strict=True)
        a = by_key(r)[("rest_and_rhythm", "days_since_last_fight", "a")]
        self.assertEqual(a["detail"]["last_fight"], "2025-09-20")
        self.assertEqual(r["coverage"]["fights_a"], 3)        # 9001, 9003, 9006

    def test_a_matchup_sheet_gives_the_same_record_as_none(self):
        sheet = mu.matchup(self.store, "101", "102", as_of="2026-10-10T23:00:00Z",
                           now="2026-10-10T16:00:00Z")
        self.assertEqual(ufc.situation_for_bout(self.store, "9101", sheet=sheet, strict=True),
                         ufc.situation_for_bout(self.store, "9101", strict=True))

    def test_the_store_is_not_modified(self):
        before = copy.deepcopy(self.store.bouts)
        ufc.situation_for_bout(self.store, "9101", strict=True)
        self.assertEqual(self.store.bouts, before)


class WhatTheDataLayerDoesNotHold(Case):
    def edit(self, store, bout_id, **fields):
        store.upsert("bouts", [dict(store.bout_by_id()[bout_id], **fields)])

    def test_a_title_bout_is_stated_when_the_schedule_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            self.edit(store, "9101", title_bout=True, bout_types=["UFC Welterweight Title"])
            t = by_key(ufc.situation_for_bout(store, "9101", strict=True))[("stakes", "title_bout", "game")]
            self.assertIs(t["value"], True)
            self.assertEqual(t["sentence"], "This is a title bout.")
            self.assertEqual(t["detail"], {"bout_types": "UFC Welterweight Title"})
            self.edit(store, "9101", title_bout=False, bout_types=[])
            t = by_key(ufc.situation_for_bout(store, "9101", strict=True))[("stakes", "title_bout", "game")]
            self.assertEqual((t["value"], t["sentence"]), (False, "This is not a title bout."))

    def test_a_move_down_and_a_move_up_in_weight(self):
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            self.edit(store, "9101", weight_class="Middleweight")            # both last fought at Welterweight
            f = by_key(ufc.situation_for_bout(store, "9101", strict=True))
            self.assertEqual(f[("availability", "weight_class_change", "a")]["value"], "up")
            self.assertEqual(f[("availability", "weight_class_change", "a")]["sentence"],
                             "Alex Archer moves up in weight, from Welterweight to Middleweight.")
            self.edit(store, "9101", weight_class="Lightweight")
            f = by_key(ufc.situation_for_bout(store, "9101", strict=True))
            self.assertEqual(f[("availability", "weight_class_change", "b")]["value"], "down")
            self.assertIn("drops down in weight", f[("availability", "weight_class_change", "b")]["sentence"])
            self.edit(store, "9101", weight_class="Catchweight")
            f = by_key(ufc.situation_for_bout(store, "9101", strict=True))
            self.assertEqual(f[("availability", "weight_class_change", "a")]["value"], "changed")

    def test_a_fighter_with_no_fights_has_gaps_not_made_up_figures(self):
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            store.upsert("fighters", [dict(store.fighter_by_id()["105"], fighter_id="106", name="Fred Fresh",
                                           aliases=["fred fresh"])])
            self.edit(store, "9101", fighter_b_id="106")
            r = ufc.situation_for_bout(store, "9101", strict=True)
            f, g = by_key(r), gaps_of(r)
            self.assertNotIn(("rest_and_rhythm", "days_since_last_fight", "b"), f)
            self.assertIn("no UFC fight in the data store", g[("rest_and_rhythm", "days_since_last_fight", "b")])
            self.assertIn(("form", "streak", "b"), g)
            self.assertEqual(f[("head_to_head", "previous_meeting", "game")]["value"], 0)
            self.assertEqual(f[("head_to_head", "previous_meeting", "game")]["sentence"],
                             "Alex Archer and Fred Fresh have not fought each other in the UFC fights on file.")
            self.assertIn(("availability", "weight_class_change", "b"), g)
            self.assertEqual(rec.problems(r), [])

    def test_a_short_turnaround_and_a_long_layoff_are_named(self):
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            self.edit(store, "9101", date_utc="2026-07-10T23:00Z")        # 27 days after Archer's 06-13 fight
            a = by_key(ufc.situation_for_bout(store, "9101", strict=True))[("rest_and_rhythm", "days_since_last_fight", "a")]
            self.assertEqual((a["value"], a["detail"]["bucket"]), (27, "short turnaround"))
            self.assertIn("a short turnaround", a["sentence"])
            self.edit(store, "9101", date_utc="2027-09-01T23:00Z")        # more than a year on
            a = by_key(ufc.situation_for_bout(store, "9101", strict=True))[("rest_and_rhythm", "days_since_last_fight", "a")]
            self.assertEqual(a["detail"]["bucket"], "long layoff")
            self.assertIn("a long layoff", a["sentence"])

    def test_a_window_that_starts_before_the_data_says_so(self):
        # the store begins 2025-01-18, so the year before a bout in mid-2025 is not all there
        r = ufc.situation_for_bout(self.store, "9006", strict=True)
        w = by_key(r)[("rest_and_rhythm", "fights_last_365_days", "a")]
        self.assertIs(w["detail"]["window_complete"], False)
        self.assertIn("where our data begins", w["sentence"])

    def test_errors_for_a_bout_that_cannot_be_read(self):
        with self.assertRaises(LookupError):
            ufc.situation_for_bout(self.store, "no-such-bout")
        with tempfile.TemporaryDirectory() as d:
            store = UF.make_store(Path(d))
            self.edit(store, "9101", date_utc=None)
            with self.assertRaises(ValueError):
                ufc.situation_for_bout(store, "9101")
            self.edit(store, "9101", date_utc="2026-10-10T23:00Z", fighter_b_id="101")
            with self.assertRaises(ValueError):
                ufc.situation_for_bout(store, "9101")

    def test_a_part_that_fails_is_listed_not_raised(self):
        from unittest import mock
        with mock.patch.object(ufc, "_form", side_effect=RuntimeError("boom")):
            r = ufc.situation_for_bout(self.store, "9101")
        self.assertTrue(any(g["family"] == "form" and "RuntimeError" in g["reason"] for g in r["missing"]))
        self.assertTrue(any(f["family"] == "stakes" for f in r["factors"]))


class TheSentences(Case):
    def records(self):
        out = [ufc.situation_for_bout(self.store, b, strict=True) for b in ("9101", "9009", "9006", "9011", "9012")]
        return out

    def test_every_number_in_every_sentence_is_held_by_its_factor(self):
        checked = 0
        for r in self.records():
            for f in r["factors"]:
                self.assertEqual(rec.unsupported_sentence_numbers(f), [], f"{f['name']}: {f['sentence']}")
                checked += 1
        self.assertGreater(checked, 60)

    def test_no_sentence_uses_a_banned_word(self):
        for r in self.records():
            for f in r["factors"]:
                for word in ("edge", "lock", "guarantee", "sure thing", "free money", "win probability"):
                    self.assertNotIn(word, f["sentence"].lower())

    def test_every_record_is_sound_and_deterministic(self):
        for bout in ("9101", "9009", "9006"):
            a = ufc.situation_for_bout(self.store, bout, strict=True)
            self.assertEqual(rec.problems(a), [])
            self.assertEqual(a, ufc.situation_for_bout(self.store, bout, strict=True))

    def test_a_sentence_the_analyst_quotes_survives_the_critics_name_check(self):
        """Fighter names inside a situation sentence are in the packet's own text, so a claim that
        repeats the sentence is not struck as an unverified person."""
        from src.analyst import ufc_analyst, ufc_packet
        packet = ufc_packet.build_packet(self.store, "9101", built_at=UF.BUILT_AT, cfg=UF.CFG)
        record = ufc.situation_for_bout(self.store, "9101", strict=True)
        packet["sections"]["situation"] = rec.packet_section(record)
        known = ufc_analyst.known_names(packet)
        for f in record["factors"]:
            self.assertEqual(critic.unsupported_names(f["sentence"], known), [], f["sentence"])


if __name__ == "__main__":
    unittest.main()
