"""L1 to L4 for V2 (build plan T3): lock-at-T-minus-4h, fresh-read
withdrawal, stale-read no-op, a withdrawn selection returning once, a locked
game pick blocking a later market on the same game, and the ceiling
counting fills alongside picks.

WHAT "A FRESH READ" MEANS FOR THIS LEDGER. `publish_v2` never re-runs a
gate itself -- it reads whatever `picks`/`prop_picks`/`fills` the caller
hands it as THIS run's fresh candidate pool (see `_lock_and_merge_v2`'s own
docstring). So "a fresh read that fails" is represented here by handing in
a candidate at the same identity carrying `failed_gates`; an entry simply
ABSENT from every list is a pool that was never re-evaluated for that key
at all (treated as stale, per `_lock_and_merge_v2`), which is why every
withdrawal test below passes an explicit failing candidate rather than
omitting one.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, select_result

FIRST_PITCH = "2026-09-20T23:00:00Z"
T_MINUS_4H = "2026-09-20T19:00:00Z"  # exactly the lock boundary


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


class LockAtFourHours(LedgerCase):
    def test_a_provisional_pick_locks_as_last_published_at_t_minus_4h(self):
        e = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                       observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[e]), now="2026-09-20T10:00:00Z", path=self.path)

        # This run's own read is FAILING (a fresh candidate at the same key
        # carrying a failed gate) -- the lock still wins, because the
        # window closed on THIS run and the entry locks as last published.
        failing = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                             observed_utc=T_MINUS_4H, failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=[failing]), now=T_MINUS_4H, path=self.path)

        self.assertEqual(1, row["n_picks"])
        self.assertTrue(row["picks"][0]["locked"])
        self.assertEqual(-140, row["picks"][0]["price"])  # last PUBLISHED price, not the failing read

    def test_a_locked_pick_is_carried_forward_verbatim_by_a_later_run(self):
        e = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                       observed_utc=T_MINUS_4H)
        first = cl.publish_v2(select_result(picks=[e]), now=T_MINUS_4H, path=self.path)
        self.assertTrue(first["picks"][0]["locked"])

        later = cl.publish_v2(select_result(picks=[]), now="2026-09-20T22:00:00Z",
                              path=self.path)
        self.assertEqual(1, later["n_picks"])
        self.assertEqual(-140, later["picks"][0]["price"])
        self.assertTrue(later["picks"][0]["locked"])


class FreshAndStaleReadsBeforeLock(LedgerCase):
    def test_a_fresh_failing_read_before_the_window_withdraws_it(self):
        e = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                       observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[e]), now="2026-09-20T10:00:00Z", path=self.path)

        fresh_fail = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                                observed_utc="2026-09-20T10:55:00Z",
                                failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=[fresh_fail]), now="2026-09-20T11:00:00Z",
                            path=self.path, fresh_seconds=3600)
        self.assertEqual(0, row["n_picks"])
        self.assertEqual(1, len(row["withdrawn"]))
        self.assertEqual(["G7_VALUE"], row["withdrawn"][0]["withdrawal_reason"])

    def test_a_stale_read_does_not_withdraw_even_when_it_would_fail(self):
        e = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                       observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[e]), now="2026-09-20T10:00:00Z", path=self.path)

        stale_fail = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                                observed_utc="2026-09-20T09:00:00Z",  # 2h old
                                failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=[stale_fail]), now="2026-09-20T11:00:00Z",
                            path=self.path, fresh_seconds=3600)
        self.assertEqual(1, row["n_picks"], "a stale read must change nothing")
        self.assertEqual(0, len(row["withdrawn"]))

    def test_a_withdrawn_selection_that_passes_again_returns_once(self):
        e = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                       observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[e]), now="2026-09-20T10:00:00Z", path=self.path)

        failing = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                             observed_utc="2026-09-20T11:00:00Z", failed_gates=["G7_VALUE"])
        withdrawn_row = cl.publish_v2(select_result(picks=[failing]), now="2026-09-20T11:00:00Z",
                                      path=self.path)
        self.assertEqual(1, len(withdrawn_row["withdrawn"]))

        passing = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                             observed_utc="2026-09-20T12:00:00Z", failed_gates=[])
        returned = cl.publish_v2(select_result(picks=[passing]), now="2026-09-20T12:00:00Z",
                                 path=self.path)
        self.assertEqual(1, returned["n_picks"])
        self.assertEqual(0, len(returned["withdrawn"]))

        again = cl.publish_v2(select_result(picks=[passing]), now="2026-09-20T12:05:00Z",
                              path=self.path)
        self.assertEqual(1, again["n_picks"], "the returned pick must not duplicate")


class LockedGameBlocksAnotherMarket(LedgerCase):
    def test_a_locked_moneyline_rejects_a_later_run_line_on_the_same_game(self):
        ml = game_entry(game_pk=1, market="moneyline", price=-140,
                        first_pitch_utc=FIRST_PITCH, observed_utc=T_MINUS_4H)
        first = cl.publish_v2(select_result(picks=[ml]), now=T_MINUS_4H, path=self.path)
        self.assertTrue(first["picks"][0]["locked"])

        rl = game_entry(game_pk=1, market="run_line", side="home", line=-1.5,
                        price=-110, first_pitch_utc=FIRST_PITCH,
                        observed_utc="2026-09-20T20:00:00Z")
        row = cl.publish_v2(select_result(picks=[rl]), now="2026-09-20T20:00:00Z", path=self.path)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual("moneyline", row["picks"][0]["market"])


class FillLockAndPromotion(LedgerCase):
    def test_a_fill_locks_the_same_way_and_is_carried_verbatim_once_locked(self):
        fill = game_entry(game_pk=1, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"], first_pitch_utc=FIRST_PITCH,
                          observed_utc=T_MINUS_4H)
        row = cl.publish_v2(select_result(fills=[fill]), now=T_MINUS_4H, path=self.path)
        self.assertEqual(1, row["n_fills"])
        self.assertTrue(row["fills"][0]["locked"])

        later = cl.publish_v2(select_result(fills=[]), now="2026-09-20T22:00:00Z",
                              path=self.path)
        self.assertEqual(1, later["n_fills"], "a locked fill must be carried forward")

    def test_a_fill_is_not_withdrawn_merely_because_picks_reach_the_floor(self):
        # 3 picks (the floor) plus a fill -- the fill must survive: nothing
        # in the ledger withdraws a fill for a reason other than a fresh
        # hard-gate failure or its identity gaining a pick.
        picks = [game_entry(game_pk=10 + i, price=-140) for i in range(3)]
        fill = game_entry(game_pk=1, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=picks, fills=[fill]),
                            now="2026-09-20T08:00:00Z", path=self.path)
        self.assertEqual(1, row["n_fills"])

    def test_a_fill_is_withdrawn_by_a_fresh_read_that_fails_a_hard_gate(self):
        fill = game_entry(game_pk=1, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"], observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(fills=[fill]), now="2026-09-20T10:00:00Z", path=self.path)

        hard_fail = game_entry(game_pk=1, price=-140, entry_class="fill",
                               failed_gates=["G4_BAND"], observed_utc="2026-09-20T11:00:00Z")
        row = cl.publish_v2(select_result(fills=[hard_fail]), now="2026-09-20T11:00:00Z",
                            path=self.path)
        self.assertEqual(0, row["n_fills"])
        self.assertEqual(1, len(row["withdrawn"]))

    def test_a_fill_whose_fresh_read_passes_every_gate_is_carried_as_a_pick(self):
        fill = game_entry(game_pk=1, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"], observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(fills=[fill]), now="2026-09-20T10:00:00Z", path=self.path)

        passing = game_entry(game_pk=1, price=-140, entry_class="pick", failed_gates=[],
                             observed_utc="2026-09-20T11:00:00Z")
        row = cl.publish_v2(select_result(picks=[passing]), now="2026-09-20T11:00:00Z",
                            path=self.path)
        self.assertEqual(1, row["n_picks"])
        self.assertEqual(0, row["n_fills"])
        self.assertEqual("pick", row["picks"][0]["entry_class"])


class CeilingCountsPicksAndFills(LedgerCase):
    """PROOF-REQUIRED INVARIANT #1 (task instructions): the ceiling of 10
    must count locked fills toward the ceiling and not just picks. The
    guarding code is `_apply_ceiling_v2`'s `candidates = unlocked_picks +
    unlocked_fills` / `room = params.ceiling - len(locked_shown)`. This
    test is run once against the real source (PASS) and once against a
    picks-only revert of that guard (FAIL) -- see the worker's own report
    for the pasted before/after `python -m unittest` output.
    """

    def test_ten_picks_plus_a_fill_refuses_the_eleventh_entry(self):
        picks = [game_entry(game_pk=100 + i, price=-140) for i in range(10)]
        fill = game_entry(game_pk=200, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=picks, fills=[fill]),
                            now="2026-09-20T08:00:00Z", path=self.path)
        self.assertEqual(10, row["n_picks"] + row["n_fills"],
                         "picks and fills together must not exceed the ceiling of 10")
        self.assertEqual(1, len(row["ceiling_refused"]))

    def test_locked_picks_and_fills_are_never_refused_by_the_ceiling(self):
        # One pick already locked from a prior run, plus 9 fresh UNLOCKED
        # picks and a fresh UNLOCKED fill this run (their own first pitch is
        # a full day out, well outside the lock window) -- the locked entry
        # must count against room but must never itself be refused.
        far_fp = "2026-09-21T23:05:00Z"
        locked_pick = game_entry(game_pk=1, price=-140, first_pitch_utc=FIRST_PITCH,
                                 observed_utc=T_MINUS_4H)
        cl.publish_v2(select_result(picks=[locked_pick]), now=T_MINUS_4H, path=self.path)

        fresh_picks = [game_entry(game_pk=100 + i, price=-140, first_pitch_utc=far_fp)
                       for i in range(9)]
        fresh_fill = game_entry(game_pk=200, price=-140, entry_class="fill",
                                first_pitch_utc=far_fp, failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=fresh_picks, fills=[fresh_fill]),
                            now="2026-09-20T20:00:00Z", path=self.path)
        self.assertTrue(any(p["game_pk"] == 1 and p["locked"] for p in row["picks"]))
        self.assertLessEqual(row["n_picks"] + row["n_fills"], 10)
        self.assertEqual(1, len(row["ceiling_refused"]),
                         "room is 10 - 1 locked = 9, so exactly one of the "
                         "9 fresh picks + 1 fresh fill must be refused")


if __name__ == "__main__":
    unittest.main()
