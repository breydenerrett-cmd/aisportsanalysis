"""The coach report card's grades: hindsight on fixture boards, the forward shadow comparison, the labels.

No network and no real ledger: every file lives in a temp directory, the boards and results are the
deterministic fixtures in ``tests/_coach_card_fixtures.py``. The stories pinned here:

  * the decision rule is the one written in docs/COACH_REPORT_CARD.md (TOO EARLY under 20 slots or 3 dates,
    then HELPED / HURT / NO DIFFERENCE by the 90% date-clustered interval), and a re-run gives the same answer;
  * hindsight replays into a TEMP ledger and never writes the real ones, and says it is hindsight;
  * the forward run bets only games whose lock came after the suggestion, never replays, and a re-run adds
    nothing;
  * a game the grader never looked at is missed by BOTH sides, so it is no slot (no phantom "pass").
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from src.hounds import coach_card as C
from src.hounds import coach_grade as G
from src.ledger.chain import HashChainLedger
from tests import _coach_card_fixtures as F


def slot(day, d):
    return {"event_id": f"e-{day}-{d}", "date": day, "c": 0.0, "s": d, "d": d}


def slots(values_by_day):
    return [slot(day, d) for day, ds in values_by_day.items() for d in ds]


class TheDecisionRule(unittest.TestCase):
    def test_under_twenty_slots_is_too_early_whatever_the_numbers(self):
        got = G.decide(slots({f"2026-10-{i:02d}": [1.0] for i in range(1, 20)}), seed=1)   # 19 slots
        self.assertEqual(got["label"], G.LABEL_EARLY)
        self.assertEqual(got["n_paired"], 19)
        self.assertIsNone(got["mean_d"])

    def test_twenty_slots_on_two_dates_is_still_too_early(self):
        got = G.decide(slots({"2026-10-01": [1.0] * 10, "2026-10-02": [1.0] * 10}), seed=1)
        self.assertEqual(got["n_paired"], 20)
        self.assertEqual(got["n_dates"], 2)
        self.assertEqual(got["label"], G.LABEL_EARLY)

    def test_an_interval_wholly_above_zero_is_helped(self):
        got = G.decide(slots({f"2026-10-{i:02d}": [1.0] for i in range(1, 21)}), seed=1)
        self.assertEqual(got["label"], G.LABEL_HELPED)
        self.assertGreater(got["ci_low"], 0)
        self.assertEqual(got["mean_d"], 1.0)

    def test_an_interval_wholly_below_zero_is_hurt(self):
        got = G.decide(slots({f"2026-10-{i:02d}": [-1.0] for i in range(1, 21)}), seed=1)
        self.assertEqual(got["label"], G.LABEL_HURT)
        self.assertLess(got["ci_high"], 0)

    def test_an_interval_around_zero_is_no_difference(self):
        # 10 dates of +1 and 10 of -1: the mean is 0 and the interval straddles it
        vals = {f"2026-10-{i:02d}": [1.0 if i % 2 else -1.0] for i in range(1, 21)}
        got = G.decide(slots(vals), seed=1)
        self.assertEqual(got["label"], G.LABEL_NONE)
        self.assertLess(got["ci_low"], 0)
        self.assertGreater(got["ci_high"], 0)

    def test_all_zero_differences_are_no_difference_not_helped(self):
        got = G.decide(slots({f"2026-10-{i:02d}": [0.0] for i in range(1, 21)}), seed=1)
        self.assertEqual(got["label"], G.LABEL_NONE)

    def test_the_same_slots_and_seed_give_the_same_interval(self):
        vals = {f"2026-10-{i:02d}": [0.4 if i % 3 else -0.7, 0.2] for i in range(1, 15)}
        a, b = G.decide(slots(vals), seed=7), G.decide(slots(vals), seed=7)
        self.assertEqual(a, b)

    def test_dates_are_resampled_together_not_slot_by_slot(self):
        """Three slots a night that move together: the clustered interval is wider than a per-slot one
        would be, because only 7 independent nights stand behind the 21 slots."""
        vals = {f"2026-10-{i:02d}": [(-1.0) ** i * 1.0] * 3 for i in range(1, 8)}
        got = G.decide(slots(vals), seed=3)
        self.assertEqual(got["n_paired"], 21)
        self.assertEqual(got["label"], G.LABEL_NONE)


class TheSlotPairing(unittest.TestCase):
    def entry(self, result, units, clv=None, day="2026-10-02"):
        return ({"date": day}, {"result": result, "units_average_price": units, "clv_pts": clv})

    def test_a_pass_counts_zero_and_a_pending_bet_waits(self):
        champ = {"a": self.entry("LOSS", -1.0), "b": self.entry(None, None), "c": self.entry("WIN", 1.1)}
        sugg = {"c": self.entry("WIN", 1.1)}
        got = G.slots_of(champ, sugg)
        by = {s["event_id"]: s for s in got["slots"]}
        self.assertEqual(by["a"]["d"], 1.0)             # the suggestion passed on a losing game
        self.assertEqual(by["c"]["d"], 0.0)
        self.assertNotIn("b", by)
        self.assertEqual(got["pending"], 1)

    def test_void_and_unresolved_bets_are_excluded_not_zeroed(self):
        champ = {"a": self.entry("VOID", 0.0), "b": self.entry("UNRESOLVED", None)}
        got = G.slots_of(champ, {})
        self.assertEqual(got["slots"], [])
        self.assertEqual(got["excluded"], 2)

    def test_the_clv_difference_uses_only_games_both_sides_bet(self):
        champ = {"a": self.entry("WIN", 1.0, clv=-2.0), "b": self.entry("LOSS", -1.0, clv=-1.0)}
        sugg = {"a": self.entry("WIN", 1.0, clv=-1.0)}
        got = G.compare(champ, sugg, seed=1)
        self.assertEqual(got["both_bet"]["games"], 1)
        self.assertEqual(got["both_bet"]["clv_diff"], 1.0)
        self.assertEqual(got["units_diff"], 1.0)           # the suggestion skipped the loser


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = F.paths_in(self.root)
        self.cfg = F.tunable_cfg()

    def grade(self, stores, now, **kw):
        return G.grade_all(self.paths, now=now, registry=F.REGISTRY, tun_cfg=self.cfg,
                           loader=lambda since, until: stores, say=lambda *_a: None, **kw)

    def play(self, stores, days):
        """One grading pass five minutes after each game's lock, as the capture slot would."""
        for day in days:
            self.grade(stores, F.lock_of(day) + timedelta(minutes=5))


class Hindsight(Base):
    def setUp(self):
        super().setUp()
        # ten past games, all lost by the home club; the suggestion is recorded the day after the last
        self.days = [F.iso_day("2026-09-20", i) for i in range(10)]
        self.stores = F.stores_for([(d, False) for d in self.days])
        self.recorded = F.start_of("2026-10-01")
        F.record(self.paths, recorded="2026-10-01T12:00:00Z")

    def test_both_value_sets_are_replayed_over_the_thirty_days_before_the_suggestion(self):
        self.grade(self.stores, self.recorded + timedelta(days=1))
        h = C.load(self.paths).hindsight[1]
        self.assertIs(h["hindsight"], True)
        self.assertEqual(h["status"], "ok")
        self.assertEqual((h["window_first"], h["window_last"], h["window_days"]), ("2026-09-01", "2026-10-01", 30))
        self.assertEqual(h["champion"]["bets"], 10)
        self.assertEqual((h["champion"]["wins"], h["champion"]["losses"]), (0, 10))
        self.assertEqual(h["champion"]["units"], -10.0)
        self.assertEqual(h["suggested"]["bets"], 0)             # a bar of +120 never clears the +110 board
        self.assertEqual(h["units_diff"], 10.0)
        self.assertEqual(h["n_paired"], 10)

    def test_a_hindsight_row_has_no_verdict_and_no_interval(self):
        self.grade(self.stores, self.recorded + timedelta(days=1))
        h = C.load(self.paths).hindsight[1]
        for key in ("label", "mean_d", "ci_low", "ci_high"):
            self.assertNotIn(key, h)

    def test_it_never_touches_the_shadow_ledger_or_writes_outside_the_card(self):
        self.grade(self.stores, self.recorded + timedelta(days=1))
        # no forward-eligible follow-up games exist, so the shadow ledger is never created by hindsight alone
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [C.LEDGER_NAME])

    def test_hindsight_is_graded_once_and_a_rerun_adds_nothing(self):
        self.grade(self.stores, self.recorded + timedelta(days=1))
        before = HashChainLedger(self.paths.ledger).read()
        self.grade(self.stores, self.recorded + timedelta(days=1, minutes=10))
        after = HashChainLedger(self.paths.ledger).read()
        self.assertEqual(len(after), len(before))

    def test_a_suggestion_whose_hound_is_unknown_gets_an_error_row_once_not_a_retry_every_slot(self):
        C.append(self.paths, C.K_SUGGESTION, now=self.recorded, **F.suggestion_row(issue=2, hound="ghost_dog"))
        self.grade(self.stores, self.recorded + timedelta(days=1))
        self.grade(self.stores, self.recorded + timedelta(days=1, minutes=10))
        rows = [r for r in HashChainLedger(self.paths.ledger).read()
                if r["kind"] == C.K_HINDSIGHT and r["issue"] == 2]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "error")

    def test_the_hindsight_window_skips_the_sealed_season(self):
        # a suggestion recorded in the sealed window would replay sealed days: those days are dropped
        first, last = G.hindsight_window({"recorded_utc": "2026-09-05T00:00:00Z"})
        self.assertEqual((first, last), ("2026-08-05", "2026-09-04"))      # Eastern dates: 00:00Z is the evening before
        self.assertEqual(G.stores_need_for_hindsight({"recorded_utc": "2026-09-05T00:00:00Z"}), "2026-08-28")


class HindsightSeal(Base):
    def test_a_sealed_day_inside_the_window_is_never_replayed(self):
        stores = F.stores_for([("2026-08-20", False), ("2026-09-02", False)])     # the first is in the sealed season
        F.record(self.paths, recorded="2026-09-05T12:00:00Z")
        self.grade(stores, C.parse("2026-09-06T12:00:00Z"))
        h = C.load(self.paths).hindsight[1]
        self.assertEqual(h["champion"]["bets"], 1)


class Forward(Base):
    def setUp(self):
        super().setUp()
        self.days = [F.iso_day("2026-10-02", i) for i in range(26)]

    def test_the_helped_story_end_to_end(self):
        stores = F.stores_for([(d, False) for d in self.days])      # the home club loses every game
        F.record(self.paths)
        self.play(stores, self.days[:5])
        early = C.load(self.paths).forward[1]
        self.assertEqual(early["label"], G.LABEL_EARLY)
        self.assertEqual(early["n_paired"], 5)
        self.assertEqual(early["units_diff"], 5.0)
        self.play(stores, self.days[5:])
        done = C.load(self.paths).forward[1]
        self.assertEqual(done["label"], G.LABEL_HELPED)
        self.assertEqual(done["n_paired"], 26)
        self.assertEqual(done["champion"]["bets"], 26)
        self.assertEqual(done["suggested"]["bets"], 0)
        self.assertEqual(done["units_diff"], 26.0)

    def test_the_hurt_story_end_to_end(self):
        stores = F.stores_for([(d, True) for d in self.days])       # the home club wins every game
        F.record(self.paths)
        self.play(stores, self.days)
        done = C.load(self.paths).forward[1]
        self.assertEqual(done["label"], G.LABEL_HURT)
        self.assertLess(done["units_diff"], 0)
        self.assertLess(done["ci_high"], 0)

    def test_no_difference_when_the_suggestion_changes_nothing(self):
        stores = F.stores_for([(d, i % 2 == 0) for i, d in enumerate(self.days)])
        F.record(self.paths, suggested=100)        # identical to the champion's value: never a real tip, but a legal row
        self.play(stores, self.days)
        done = C.load(self.paths).forward[1]
        self.assertEqual(done["label"], G.LABEL_NONE)
        self.assertEqual(done["units_diff"], 0.0)

    def test_a_rerun_in_the_same_minute_appends_nothing(self):
        stores = F.stores_for([(d, False) for d in self.days[:3]])
        F.record(self.paths)
        now = F.lock_of(self.days[0]) + timedelta(minutes=5)
        self.grade(stores, now)
        n = len(HashChainLedger(self.paths.ledger).read())
        shadow_n = len(HashChainLedger(self.paths.shadow).read())
        self.grade(stores, now)
        self.assertEqual(len(HashChainLedger(self.paths.ledger).read()), n)
        self.assertEqual(len(HashChainLedger(self.paths.shadow).read()), shadow_n)

    def test_a_game_whose_lock_came_before_the_suggestion_is_not_bet(self):
        stores = F.stores_for([(d, False) for d in self.days[:3]])
        F.record(self.paths, recorded=F.iso_day(self.days[1], 0) + "T00:00:00Z")
        for d in self.days[:3]:
            self.grade(stores, F.lock_of(d) + timedelta(minutes=5))
        rows = [r for r in HashChainLedger(self.paths.shadow).read() if r["kind"] == "hound_bet"]
        self.assertEqual({r["date"] for r in rows}, {self.days[1], self.days[2]})     # not the first day
        self.assertTrue(all(r["segment"] == "forward" for r in rows))

    def test_nothing_is_ever_replayed_a_started_game_is_not_bet_by_the_forward_run(self):
        stores = F.stores_for([(self.days[0], False)])
        F.record(self.paths)
        self.grade(stores, F.start_of(self.days[0]) + timedelta(minutes=1))
        self.assertFalse(self.paths.shadow.exists() and
                         [r for r in HashChainLedger(self.paths.shadow).read() if r["kind"] == "hound_bet"])

    def test_a_game_the_grader_never_saw_is_missed_by_both_sides_so_it_is_no_slot(self):
        stores = F.stores_for([(d, False) for d in self.days[:6]])
        F.record(self.paths)
        for d in self.days[:6]:
            if d == self.days[2]:
                continue                                     # the slot for this day never ran
            self.grade(stores, F.lock_of(d) + timedelta(minutes=5))
        fwd = C.load(self.paths).forward[1]
        self.assertEqual(fwd["n_paired"], 5)
        self.assertEqual(fwd["champion"]["bets"], 5)         # not 6 bets against 5 "passes"
        self.assertEqual(fwd["units_diff"], 5.0)

    def test_the_rows_say_whose_they_are_and_both_ledgers_verify(self):
        stores = F.stores_for([(d, False) for d in self.days[:2]])
        F.record(self.paths)
        self.play(stores, self.days[:2])
        bets = [r for r in HashChainLedger(self.paths.shadow).read() if r["kind"] == "hound_bet"]
        self.assertEqual({r["hound_id"] for r in bets}, {"coach-1-champion"})
        self.assertTrue(all(r["role"] == "coach_practice" and r["coach_issue"] == 1 and
                            r["parent_hound_id"] == "fake_dog" for r in bets))
        self.assertTrue(HashChainLedger(self.paths.shadow).verify().ok)
        self.assertTrue(HashChainLedger(self.paths.ledger).verify().ok)

    def test_a_suggestion_older_than_the_follow_window_is_no_longer_run(self):
        F.record(self.paths, recorded="2026-10-01T00:00:00Z")
        card = C.load(self.paths)
        fresh = G.active_for_forward(card, C.parse("2026-10-01T00:00:00Z") + timedelta(days=G.FORWARD_MAX_DAYS))
        stale = G.active_for_forward(card, C.parse("2026-10-01T00:00:00Z") + timedelta(days=G.FORWARD_MAX_DAYS + 1))
        self.assertEqual(len(fresh), 1)
        self.assertEqual(stale, [])

    def test_the_time_budget_stops_between_stages_and_leaves_the_rest_for_the_next_slot(self):
        stores = F.stores_for([(self.days[0], False)])
        F.record(self.paths)
        out = G.grade_all(self.paths, now=F.lock_of(self.days[0]) + timedelta(minutes=5), registry=F.REGISTRY,
                          tun_cfg=self.cfg, loader=lambda s, u: stores, deadline=0.0, clock=lambda: 1.0,
                          say=lambda *_a: None)
        self.assertEqual(out["hindsight"], 0)
        self.assertIn("time budget", out["stopped"])
        self.assertEqual(C.load(self.paths).hindsight, {})


if __name__ == "__main__":
    unittest.main()
