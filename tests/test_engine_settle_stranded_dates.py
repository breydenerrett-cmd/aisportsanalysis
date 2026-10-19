"""Paper wagers stranded for a month: the 2026-10-19 grading-gap regression.

On 2026-10-19 the site showed 11 Setter bets dated 2026-09-22 with no result.
They were not Setter's alone: 505 paper wagers (every engine system, so the
five signal hounds and the three baselines among them) on three dates
(09-17: 68, 09-22: 323, 09-27: 108) had never been graded, though every one of
those games was played and sat in the results store. Three different reasons
the one-shot `engine settle --date <yesterday>` exited 2 on its day, and one
reason none of them was ever retried:

  * 09-17  six wagers on an NFL event (fixed 09-21, but only for dates settled
           after it);
  * 09-22  TOR at BAL (824785) was rained out and played the next day under the
           same game_pk (the makeup handling arrived 10-17);
  * 09-27  BAL at NYY (823490) was CANCELLED with no makeup: no result, ever,
           and the settle step refuses a whole date while any game lacks one;
  * the retry (`engine settle --recent`, added 10-17) only looked 2-7 days
    back, so by the time it existed all three dates were 20-30 days old and
    nothing opened them again.

What these tests pin:

  1. a game the schedule shows as ONLY Cancelled is voided by name and the
     date's other games settle in the same run (the 09-27 case);
  2. nothing short of that positive evidence voids anything (a Postponed or
     Suspended entry, a failed call, an empty answer: the refusal stands);
  3. the carried sweep reaches back to the first paper day, not a week, so a
     date that was missed once is settled by the next morning's loop (09-22).

Everything is injected: temp ledgers, fake schedule lookups, no network.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from unittest import mock

from src import cli
from src.engine import settle_slate
from src.ledger.chain import HashChainLedger
from src.pipeline import history
from tests.test_engine_settle import (
    SYSTEM, SettleTestBase, _wager_row, _write_jsonl, _write_results_csv)

PLAYED_PK = 900101          # BAL at NYY's neighbours: played, final
CANCELLED_PK = 823490       # BAL at NYY, 2026-09-27, Cancelled, no makeup
DAY = "2026-09-27"


def _inst(state, detailed, date, pk=CANCELLED_PK):
    return {"game_pk": pk, "date": date, "state": state, "detailed_state": detailed}


CANCELLED = _inst("cancelled", "Cancelled", DAY)


_REAL_CANCELLED_GAME = history.cancelled_game     # captured before any test patches the module


def _cancelled_lookup(instances):
    return lambda pk, day: _REAL_CANCELLED_GAME(pk, day, fetch_instances=lambda _pk: instances)


class CancelledGameEvidence(unittest.TestCase):
    def test_a_lone_cancelled_entry_is_positive_evidence(self):
        info = history.cancelled_game(CANCELLED_PK, DAY, fetch_instances=lambda _: [CANCELLED])
        self.assertEqual(info["status"], history.CANCELLED_NEVER_PLAYED)
        self.assertEqual(info["game_pk"], str(CANCELLED_PK))
        self.assertIn("never played", info["detail"])

    def test_nothing_else_is_evidence(self):
        def down(_pk):
            raise OSError("schedule unreachable")

        cases = {
            "postponed (resumes under the same pk)": [_inst("cancelled", "Postponed", "2026-09-28")],
            "suspended (resumes)": [_inst("cancelled", "Suspended", DAY)],
            "played": [_inst("final", "Final", DAY)],
            "in progress": [_inst("pending", "In Progress", DAY)],
            "cancelled but a later entry exists": [CANCELLED, _inst("pending", "Scheduled", "2026-09-28")],
            "postponed then cancelled": [_inst("cancelled", "Postponed", DAY), CANCELLED],
            "empty answer": [],
        }
        for label, instances in cases.items():
            self.assertIsNone(
                history.cancelled_game(CANCELLED_PK, DAY, fetch_instances=lambda _, i=instances: i), label)
        self.assertIsNone(history.cancelled_game(CANCELLED_PK, DAY, fetch_instances=down))
        self.assertIsNone(history.cancelled_game(CANCELLED_PK, "not-a-date", fetch_instances=lambda _: [CANCELLED]))


class CancelledGameDoesNotBlockTheDate(SettleTestBase):
    """The 2026-09-27 shape: one cancelled game used to keep every wager on the date ungraded."""

    def setUp(self):
        super().setUp()
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-played", PLAYED_PK, 150, date_str=DAY, selection_id="sel-p"),
            _wager_row("bet-cancelled", CANCELLED_PK, -110, date_str=DAY, selection_id="sel-c"),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": PLAYED_PK, "date": DAY, "home_score": 5, "away_score": 2}])

    def _rows(self):
        return HashChainLedger(self.account_ledger_path_fn(SYSTEM)).read()

    def test_control_without_a_lookup_the_whole_date_still_refuses(self):
        with self.assertRaises(settle_slate.SettleError) as ctx:
            self.run_settle(DAY)
        self.assertIn("partial slate", str(ctx.exception))
        self.assertFalse(self.account_ledger_path_fn(SYSTEM).exists())

    def test_the_cancelled_game_is_voided_by_name_and_the_rest_settles(self):
        report = self.run_settle(DAY, cancelled_lookup=_cancelled_lookup([CANCELLED]))
        rows = {r["bet_id"]: r for r in self._rows()}
        self.assertEqual(rows["bet-played"]["outcome"], "win")
        void = rows["bet-cancelled"]
        self.assertEqual(void["outcome"], "void")
        self.assertEqual(void["profit_units"], 0.0)
        self.assertEqual(void["game_pk"], str(CANCELLED_PK))
        self.assertIn("cancelled and never played", void["void_reason"])
        self.assertEqual(len(report.voided_cancelled), 1)
        self.assertEqual(report.voided_cancelled[0]["bet_id"], "bet-cancelled")

    def test_a_rerun_settles_nothing_twice(self):
        look = _cancelled_lookup([CANCELLED])
        self.run_settle(DAY, cancelled_lookup=look)
        again = self.run_settle(DAY, cancelled_lookup=look)
        self.assertEqual(sum(len(s.settled) for s in again.systems), 0)
        self.assertEqual(again.voided_cancelled, ())
        self.assertEqual(len(self._rows()), 2)

    def test_no_positive_evidence_still_refuses_and_writes_nothing(self):
        for label, instances in {
                "postponed with no new date": [_inst("cancelled", "Postponed", DAY)],
                "suspended": [_inst("cancelled", "Suspended", DAY)],
                "empty answer": []}.items():
            with self.assertRaises(settle_slate.SettleError, msg=label):
                self.run_settle(DAY, cancelled_lookup=_cancelled_lookup(instances),
                                makeup_lookup=None)
        self.assertFalse(self.account_ledger_path_fn(SYSTEM).exists())

    def test_a_game_with_a_result_is_never_asked_about(self):
        asked = []
        self.run_settle(DAY, cancelled_lookup=lambda pk, day: asked.append(pk) or
                        _REAL_CANCELLED_GAME(pk, day, fetch_instances=lambda _: [CANCELLED]))
        self.assertEqual(asked, [str(CANCELLED_PK)])


class TheCarriedSweepReachesBackToTheFirstPaperDay(SettleTestBase):
    """The 2026-09-22 shape: a date missed on its own morning was never opened again once it was 8+ days old."""

    MISSED = "2026-09-22"
    ANCHOR = "2026-10-19"           # 27 days later: far outside the old 2-7 day window

    def setUp(self):
        super().setUp()
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-old", PLAYED_PK, 116, date_str=self.MISSED, selection_id="sel-old"),
            # before the first paper day: never owed, never opened
            _wager_row("bet-sealed", PLAYED_PK + 1, 100, date_str="2026-08-30", selection_id="sel-s"),
        ])
        _write_results_csv(self.results_path, [
            {"game_pk": PLAYED_PK, "date": self.MISSED, "home_score": 4, "away_score": 2},
            {"game_pk": PLAYED_PK + 1, "date": "2026-08-30", "home_score": 1, "away_score": 0},
        ])
        real_run = settle_slate.run_settle
        real_wagers = settle_slate.wagers_for_date
        real_ids = settle_slate.already_settled_bet_ids

        def run(date_str, **kw):
            for name, value in (
                    ("game_pk_map_path", self.game_pk_map_path), ("sport_source_paths", ()),
                    ("wagers_path", self.wagers_path), ("results_path", self.results_path),
                    ("f5_historical_path", self.f5_path), ("boxscores_glob", self.boxscores_glob),
                    ("information_events_path", self.info_events_path),
                    ("decisions_path", self.decisions_path), ("review_path", self.review_path),
                    ("scorecard_path", self.scorecard_path),
                    ("account_ledger_path_fn", self.account_ledger_path_fn)):
                kw.setdefault(name, value)
            return real_run(date_str, **kw)

        for patch in (
                mock.patch.object(settle_slate, "run_settle", side_effect=run),
                mock.patch.object(settle_slate, "wagers_for_date", side_effect=lambda d, path=None: real_wagers(
                    d, path=path or str(self.wagers_path))),
                mock.patch.object(settle_slate, "already_settled_bet_ids", side_effect=lambda s, fn=None: real_ids(
                    s, fn or self.account_ledger_path_fn)),
                mock.patch.object(history, "postponed_makeup", return_value=None),
                mock.patch.object(history, "cancelled_game", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def _sweep(self, anchor):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli._cmd_engine_settle(argparse.Namespace(date=anchor, recent=True))
        return code, out.getvalue(), err.getvalue()

    def test_a_date_27_days_old_is_settled_by_the_sweep(self):
        code, out, err = self._sweep(self.ANCHOR)
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("1 earlier date(s) still owed", out)
        rows = HashChainLedger(self.account_ledger_path_fn(SYSTEM)).read()
        self.assertEqual([r["bet_id"] for r in rows], ["bet-old"])
        self.assertEqual(rows[0]["outcome"], "win")

    def test_the_next_sweep_opens_nothing(self):
        self._sweep(self.ANCHOR)
        code, out, _ = self._sweep("2026-10-20")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("0 earlier date(s) still owed", out)
        self.assertEqual(len(HashChainLedger(self.account_ledger_path_fn(SYSTEM)).read()), 1)

    def test_a_true_gap_that_old_still_fails_the_sweep_so_the_loop_escalates(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-gap", 900777, 150, date_str=self.MISSED, selection_id="sel-gap")])
        code, _, err = self._sweep(self.ANCHOR)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("900777", err)

    def test_the_sweep_is_wired_to_the_cancelled_lookup(self):
        _write_jsonl(self.wagers_path, [
            _wager_row("bet-c", CANCELLED_PK, 150, date_str=DAY, selection_id="sel-c")])
        with mock.patch.object(history, "cancelled_game",
                               side_effect=_cancelled_lookup([CANCELLED])):
            code, out, err = self._sweep(self.ANCHOR)
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("voided (game cancelled, never played): bet-c", out)


if __name__ == "__main__":
    unittest.main()
