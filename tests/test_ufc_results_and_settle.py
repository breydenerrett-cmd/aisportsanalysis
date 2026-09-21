"""Tests for the manual UFC results store (src/pipeline/ufc_results.py) and
UFC card settlement (src/report/ufc_card.py), including the `ufc result`
CLI and grading VOID cases (docs/PREREG_UFC_CARD_V1.md items 8 and 10).
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import card_ledger
from src.pipeline import ufc_results
from src.report import ufc_card as ufc_report

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
DATE = "2026-09-26"


class SplitAndMatch(unittest.TestCase):
    def test_split_fight_parses_a_vs_b(self):
        self.assertEqual(ufc_results.split_fight("Jon Jones vs Tom Aspinall"),
                         ("Jon Jones", "Tom Aspinall"))

    def test_fighters_match_is_order_insensitive_and_case_insensitive(self):
        self.assertTrue(ufc_results.fighters_match(
            "tom aspinall vs JON JONES", "Jon Jones", "Tom Aspinall"))

    def test_fighters_match_false_on_a_different_pair(self):
        self.assertFalse(ufc_results.fighters_match(
            "Someone Else vs Jon Jones", "Jon Jones", "Tom Aspinall"))


class RecordResultCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ufc_results.jsonl"

    def test_record_and_read_back(self):
        row = ufc_results.record_result(
            date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Jon Jones",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@linehound.app",
            now=NOW, path=self.path)
        self.assertEqual(row["winner"], "Jon Jones")
        self.assertEqual(row["entered_by"], "ops@linehound.app")
        self.assertIn("entered_utc", row)

        found = ufc_results.result_for_fight(DATE, "Jon Jones", "Tom Aspinall",
                                              path=self.path)
        self.assertIsNotNone(found)
        self.assertEqual(found["winner"], "Jon Jones")

    def test_winner_must_be_one_of_the_two_named_fighters(self):
        with self.assertRaises(ufc_results.UfcResultsError):
            ufc_results.record_result(
                date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Someone Else",
                outcome=ufc_results.OUTCOME_WIN, entered_by="ops@linehound.app",
                now=NOW, path=self.path)

    def test_win_requires_a_winner(self):
        with self.assertRaises(ufc_results.UfcResultsError):
            ufc_results.record_result(
                date=DATE, fight="Jon Jones vs Tom Aspinall", winner=None,
                outcome=ufc_results.OUTCOME_WIN, entered_by="ops@linehound.app",
                now=NOW, path=self.path)

    def test_draw_ignores_winner_and_is_void_outcome(self):
        row = ufc_results.record_result(
            date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Jon Jones",
            outcome=ufc_results.OUTCOME_DRAW, entered_by="ops@linehound.app",
            now=NOW, path=self.path)
        self.assertIsNone(row["winner"])
        self.assertIn(row["outcome"], ufc_results.VOID_OUTCOMES)

    def test_entered_by_is_required(self):
        with self.assertRaises(ufc_results.UfcResultsError):
            ufc_results.record_result(
                date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Jon Jones",
                outcome=ufc_results.OUTCOME_WIN, entered_by="", now=NOW, path=self.path)

    def test_a_correction_is_a_new_row_and_the_newest_wins(self):
        ufc_results.record_result(
            date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Jon Jones",
            outcome=ufc_results.OUTCOME_WIN, entered_by="a@x.com", now=NOW, path=self.path)
        ufc_results.record_result(
            date=DATE, fight="Jon Jones vs Tom Aspinall", winner="Tom Aspinall",
            outcome=ufc_results.OUTCOME_WIN, entered_by="b@x.com",
            now=NOW + timedelta(minutes=5), path=self.path)
        found = ufc_results.result_for_fight(DATE, "Jon Jones", "Tom Aspinall",
                                              path=self.path)
        self.assertEqual(found["winner"], "Tom Aspinall")
        self.assertEqual(len(ufc_results.results_for_date(DATE, path=self.path)), 2)


class SettleForDate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger_path = Path(self.tmp.name) / "cards_mma.jsonl"
        self.results_path = Path(self.tmp.name) / "ufc_results.jsonl"

    def _publish_one_pick(self, *, home="Fighter A", away="Fighter B",
                          side="home", price=-150.0):
        commence = (NOW - timedelta(hours=3)).isoformat()
        card = {
            "date": DATE, "sport": "mma", "rule": ufc_report.RULE_ID,
            "picks": [{
                "game_id": "bout1", "rank": 1, "sport": "mma",
                "home_team": home, "away_team": away, "side": side,
                "team": home if side == "home" else away, "market": "moneyline",
                "line": None, "price": price, "book": "consensus",
                "market_probability": 0.62, "model_probability": None,
                "label": "FAVOURITE", "bet": "test bet", "why": ["test"],
                "kickoff_utc": commence, "first_pitch_utc": commence,
                "experimental": True,
            }],
            "count": 1,
        }
        return card_ledger.publish(card, now=NOW.isoformat(), path=self.ledger_path, sport="mma")

    def test_win_grades_win_at_the_consensus_price(self):
        self._publish_one_pick(side="home", price=-150.0)
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", winner="Fighter A",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@x.com",
            now=NOW, path=self.results_path)

        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertIsNotNone(row)
        self.assertEqual(row["wins"], 1)
        self.assertEqual(row["losses"], 0)
        self.assertGreater(row["profit_units"], 0)

    def test_loss_grades_loss(self):
        self._publish_one_pick(side="home", price=-150.0)
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", winner="Fighter B",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@x.com",
            now=NOW, path=self.results_path)

        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["wins"], 0)
        self.assertEqual(row["losses"], 1)
        self.assertEqual(row["profit_units"], -1.0)

    def test_draw_voids_the_pick(self):
        self._publish_one_pick()
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", outcome=ufc_results.OUTCOME_DRAW,
            entered_by="ops@x.com", now=NOW, path=self.results_path)
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["voids"], 1)
        self.assertEqual(row["wins"], 0)
        self.assertEqual(row["losses"], 0)

    def test_no_contest_voids_the_pick(self):
        self._publish_one_pick()
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", outcome=ufc_results.OUTCOME_NO_CONTEST,
            entered_by="ops@x.com", now=NOW, path=self.results_path)
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["voids"], 1)

    def test_cancelled_voids_the_pick(self):
        self._publish_one_pick()
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", outcome=ufc_results.OUTCOME_CANCELLED,
            entered_by="ops@x.com", now=NOW, path=self.results_path)
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["voids"], 1)

    def test_fighter_change_voids_the_pick(self):
        # The locked pick was Fighter A vs Fighter B; the result entered is
        # for a completely different pairing (a late replacement) -- no
        # result matches the locked pick's names, so it grades VOID.
        self._publish_one_pick()
        ufc_results.record_result(
            date=DATE, fight="Someone New vs Fighter B", winner="Someone New",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@x.com",
            now=NOW, path=self.results_path)
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["voids"], 1)
        self.assertEqual(row["wins"], 0)
        self.assertEqual(row["losses"], 0)

    def test_no_result_entered_yet_voids_rather_than_loses(self):
        self._publish_one_pick()
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertEqual(row["voids"], 1)
        self.assertEqual(row["losses"], 0)

    def test_settling_twice_is_a_noop(self):
        self._publish_one_pick()
        ufc_results.record_result(
            date=DATE, fight="Fighter A vs Fighter B", winner="Fighter A",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@x.com",
            now=NOW, path=self.results_path)
        first = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                           results_path=self.results_path)
        self.assertIsNotNone(first)
        second = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                            results_path=self.results_path)
        self.assertIsNone(second)

    def test_nothing_published_settles_to_none(self):
        row = ufc_report.settle_for_date(DATE, now=NOW, path=self.ledger_path,
                                         results_path=self.results_path)
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
