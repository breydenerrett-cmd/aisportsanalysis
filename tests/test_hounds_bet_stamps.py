"""The two stamps that ride on every bet row (src/hounds/contract.py BetRow): ``start_utc`` (first pitch) and
``recorded_utc`` (when the row was WRITTEN). They are what the dog page's "on the record before the game" line
compares, so the rule here is the whole claim: recorded_utc is a write time, never the lock deadline, and the
graded row written days later never overwrites it.
"""

from __future__ import annotations

import unittest

from src.hounds import contract, ledgers, stats


def bet_row(**over):
    row = {"kind": "hound_bet", "hound_id": "steamy_setter", "date": "2026-10-17", "sport": "mlb",
           "event_id": "e1", "market": "moneyline", "selection": "Boston Red Sox ML", "side": "home",
           "price_average": -115, "price_best": -110, "book": "bookA", "book_count": 7, "consensus_fair": 0.52,
           "reason": "The market moved.", "who_decided": "rule", "segment": "forward",
           "start_utc": "2026-10-17T23:10:00Z", "lock_utc": "2026-10-17T22:10:00Z",
           "written_utc": "2026-10-17T19:00:00Z", "row_hash": "h1"}
    row.update(over)
    return row


def graded_row(**over):
    row = {"kind": "hound_graded", "hound_id": "steamy_setter", "date": "2026-10-17", "bet_row_hash": "h1",
           "result": "win", "units_best_price": 0.91, "written_utc": "2026-10-19T08:00:00Z", "row_hash": "h2"}
    row.update(over)
    return row


class TheStamps(unittest.TestCase):
    def merged(self, *rows):
        bets, _defs = ledgers.pack_rows(list(rows))
        self.assertEqual(len(bets), 1, "a bet and its grade are one bet")
        return bets[0]

    def test_a_pack_row_carries_its_start_and_its_write_time(self):
        bet = self.merged(bet_row())
        self.assertEqual((bet.start_utc, bet.recorded_utc), ("2026-10-17T23:10:00Z", "2026-10-17T19:00:00Z"))

    def test_the_lock_deadline_is_not_a_record_time(self):
        bet = self.merged(bet_row(written_utc=None))
        self.assertIsNone(bet.recorded_utc)
        self.assertEqual(bet.decision_utc, "2026-10-17T22:10:00Z")        # the deadline is still kept, as before

    def test_the_grade_written_days_later_does_not_overwrite_the_write_time(self):
        bet = self.merged(bet_row(), graded_row())
        self.assertEqual(bet.result, "win")
        self.assertEqual(bet.recorded_utc, "2026-10-17T19:00:00Z")

    def test_a_user_engine_row_uses_its_recorded_utc(self):
        bet = self.merged(bet_row(written_utc=None, recorded_utc="2026-10-17T18:30:00Z"))
        self.assertEqual(bet.recorded_utc, "2026-10-17T18:30:00Z")

    def test_both_reach_the_public_row(self):
        bet = self.merged(bet_row())
        row = contract.to_json(stats.bet_row(bet, None))
        self.assertEqual((row["start_utc"], row["recorded_utc"]), ("2026-10-17T23:10:00Z", "2026-10-17T19:00:00Z"))

    def test_a_row_with_neither_says_none_not_a_guess(self):
        row = contract.to_json(contract.BetRow(hound_id="x", date="2026-10-17"))
        self.assertIsNone(row["start_utc"])
        self.assertIsNone(row["recorded_utc"])


if __name__ == "__main__":
    unittest.main()
