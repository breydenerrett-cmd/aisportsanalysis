"""NHL pre-lock capture (docs/NHL_LOCK_CAPTURE.md).

A member dog checks a game at its lock (start minus 60/120/180 minutes) and refuses a board older than
user_engine.MAX_BOARD_AGE_MINUTES. The all-sports phases (t24h, t6h, t2h, t30m) left no board between 6 hours and
2 hours before a puck drop, so a 180-minute lock found a board 3 hours old. These tests pin the extra capture 45
minutes before each lock choice and the credit reserve that keeps the day's cap from being spent before the locks.
"""
from __future__ import annotations

import json
import unittest

from src.capture import budget
from src.hounds import user_engine as eng
from src.pipeline import allsports_capture as ac
from src.sports import catalog
from tests._allsports_fixtures import NOW, raw_event, read_jsonl, minutes, sport_entry
from tests.test_allsports_capture import NBA, Base

NHL = "icehockey_nhl"
LOCK = 180


class NhlLockCapture(Base):
    def nhl_game(self, start_in_minutes, event_id="n1"):
        return raw_event(event_id, "Boston Bruins", "New York Rangers", NOW + minutes(start_in_minutes),
                         total=(5.5, -110, -110), spread=(-1.5, 150, -180))

    def nhl_fake(self, start_in_minutes):
        return self.fake({NHL: [self.nhl_game(start_in_minutes)]}, sports=[sport_entry(NHL, group="Ice Hockey")])

    def test_catalog_flags_nhl_only(self):
        self.assertEqual(catalog.lock_phases("NHL"), {"lock60": 105, "lock120": 165, "lock180": 225})
        self.assertEqual(catalog.lock_phases("NBA"), {})
        self.assertEqual(catalog.lock_phases("HOCKEY"), {})

    def test_a_board_is_bought_inside_the_lock_window_and_is_fresh_at_a_180_minute_lock(self):
        start = 300                                    # puck drop 300 minutes after NOW: t6h opens now
        fake = self.nhl_fake(start)
        self.go(fake)                                  # the t6h board
        self.assertEqual(len(fake.odds_calls), 1)
        quiet = self.go(fake, now=NOW + minutes(30))   # 270 minutes out: nothing is due
        self.assertEqual(quiet["calls"], [])
        pre_lock = self.go(fake, now=NOW + minutes(start - 215))   # 215 minutes out: lock180 (225) is open
        self.assertEqual(len(pre_lock["calls"]), 1)
        marked = {(r["event_id"], r["phase"]) for r in read_jsonl(self.paths.done) if r["kind"] == "phase"}
        self.assertIn(("n1", "lock180"), marked)
        # the engine's own freshness rule at the lock instant
        rows = eng.load_rows("2026-10-20", ["NHL"], multibook_path=self.paths.multibook)
        game = eng.build_games(rows, near_date="2026-10-20")["n1"]
        lock_utc = NOW + minutes(start - LOCK)
        found = game.board_at("moneyline", lock_utc)
        self.assertIsNotNone(found)
        observed, _board = found
        age = (lock_utc - observed).total_seconds() / 60.0
        self.assertLessEqual(age, game.board_max_age())
        self.assertLessEqual(age, 45.5)

    def test_the_other_two_lock_choices_get_their_own_boards(self):
        start = 300
        fake = self.nhl_fake(start)
        self.go(fake)
        self.go(fake, now=NOW + minutes(start - 215))                  # lock180
        self.assertEqual(len(self.go(fake, now=NOW + minutes(start - 160))["calls"]), 1)     # lock120 (165)
        self.assertEqual(len(self.go(fake, now=NOW + minutes(start - 100))["calls"]), 1)     # lock60 (105)
        self.assertEqual(len(fake.odds_calls), 4)

    def test_a_family_without_the_flag_gets_no_extra_capture(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        extra = self.go(fake, now=NOW + minutes(300 - 215))
        self.assertEqual(extra["calls"], [])
        self.assertEqual(len(fake.odds_calls), 1)

    def test_one_call_marks_every_lock_phase_already_open(self):
        fake = self.nhl_fake(90)                       # first seen 90 minutes out: every phase is open at once
        result = self.go(fake)
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(result["calls"][0]["phases_marked"], 6)       # t24h t6h t2h + lock60/120/180 (t30m not yet)
        self.assertEqual(len(fake.odds_calls), 1)


class ReserveHeldForLocks(Base):
    def spend_today(self, credits):
        with open(self.paths.credit, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 80000,
                                 "credits_used_last": credits, "caller": "allsports_capture.pregame",
                                 "budget_band": "allsports_capture"}) + "\n")

    def test_the_reserve_default_is_ninety(self):
        self.assertEqual(catalog.capture_config()["lock_reserve_credits"], 90)

    def test_a_non_lock_call_cannot_spend_the_reserve_but_a_lock_call_can(self):
        self.spend_today(1450)                         # cap 1500, reserve 90: ordinary calls stop at 1410
        nhl = raw_event("n1", "Boston Bruins", "New York Rangers", NOW + minutes(200), total=(5.5, -110, -110))
        fake = self.fake({NBA: [self.nba_game(300)], NHL: [nhl]},
                         sports=[sport_entry(NBA), sport_entry(NHL, group="Ice Hockey")])
        result = self.go(fake)
        self.assertEqual([c[0] for c in fake.odds_calls], [NHL])       # the lock call went, NBA did not
        self.assertIn("pre-lock reserve", result["skipped"][NBA])
        self.assertIsNone(result["halt"])              # skipping one call is not a halt

    def test_the_hard_cap_still_halts_even_a_lock_call(self):
        self.spend_today(1499)
        nhl = raw_event("n1", "Boston Bruins", "New York Rangers", NOW + minutes(200), total=(5.5, -110, -110))
        fake = self.fake({NHL: [nhl]}, sports=[sport_entry(NHL, group="Ice Hockey")])
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [])
        self.assertIn("daily cap", result["halt"])

    def test_budget_reserve_zero_changes_nothing(self):
        self.spend_today(1495)
        self.assertTrue(budget.can_spend_allsports(3, now=NOW, store=self.paths.credit, remaining=80000).allowed)
        refused = budget.can_spend_allsports(3, now=NOW, store=self.paths.credit, remaining=80000, reserve=90)
        self.assertFalse(refused.allowed)
        self.assertNotIn("daily cap", refused.reason)


if __name__ == "__main__":
    unittest.main()
