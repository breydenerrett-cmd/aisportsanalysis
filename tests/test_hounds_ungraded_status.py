"""A ticket 36+ hours past its start with no grade is UNGRADED, never open (2026-10-19).

On 2026-10-19 a model page listed 11 bets dated 2026-09-22 as open. The bets had been skipped by the settler
(tests/test_engine_settle_stranded_dates.py); the display must not have said "open" about a month-old bet whatever
the cause. These tests pin the rule at its boundary, the unknown-start fallback to the slate date, and that the
API payload, the open/ungraded filters and the model's counts all agree.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.hounds import contract, ledgers, stats
from src.hounds.contract import (
    BetRow, StreamItem, TICKET_GRADED, TICKET_OPEN, TICKET_UNGRADED, filter_by_status, ticket_status,
    with_status)

START = datetime(2026, 9, 22, 23, 10, tzinfo=timezone.utc)
START_TEXT = "2026-09-22T23:10:00Z"


def at(hours_after_start: float) -> datetime:
    return START + timedelta(hours=hours_after_start)


class TheBoundary(unittest.TestCase):
    def test_just_inside_36_hours_is_open(self):
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-22", at(35.99)), TICKET_OPEN)

    def test_exactly_36_hours_is_still_open(self):
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-22", at(36)), TICKET_OPEN)

    def test_a_second_past_36_hours_is_ungraded(self):
        now = at(36) + timedelta(seconds=1)
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-22", now), TICKET_UNGRADED)

    def test_a_month_old_bet_is_ungraded(self):
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-22", at(24 * 27)), TICKET_UNGRADED)

    def test_a_graded_ticket_is_graded_however_old(self):
        self.assertEqual(ticket_status("win", START_TEXT, "2026-09-22", at(24 * 90)), TICKET_GRADED)
        self.assertEqual(ticket_status("void", None, "2026-09-22", at(24 * 90)), TICKET_GRADED)

    def test_a_future_game_is_open(self):
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-22", at(-5)), TICKET_OPEN)

    def test_an_offset_stamp_reads_the_same_as_z(self):
        now = at(36) + timedelta(minutes=1)
        self.assertEqual(ticket_status(None, "2026-09-22T19:10:00-04:00", "2026-09-22", now), TICKET_UNGRADED)


class UnknownStartUsesTheSlateDate(unittest.TestCase):
    """The slate date stands in for the start, counted as the END of that UTC day."""

    END_OF_DAY = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)

    def test_exactly_36_hours_after_the_slate_day_closed_is_open(self):
        self.assertEqual(ticket_status(None, None, "2026-09-22", self.END_OF_DAY + timedelta(hours=36)), TICKET_OPEN)

    def test_past_it_is_ungraded(self):
        now = self.END_OF_DAY + timedelta(hours=36, seconds=1)
        self.assertEqual(ticket_status(None, None, "2026-09-22", now), TICKET_UNGRADED)

    def test_the_slate_day_itself_is_open(self):
        self.assertEqual(ticket_status(None, None, "2026-09-22", datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)),
                         TICKET_OPEN)

    def test_an_unreadable_start_falls_back_to_the_date(self):
        now = self.END_OF_DAY + timedelta(days=30)
        self.assertEqual(ticket_status(None, "not a time", "2026-09-22", now), TICKET_UNGRADED)

    def test_no_start_and_no_date_is_never_claimed_ungraded(self):
        self.assertEqual(ticket_status(None, None, "", at(24 * 400)), TICKET_OPEN)
        self.assertEqual(ticket_status(None, None, None, at(24 * 400)), TICKET_OPEN)

    def test_a_known_start_beats_the_date(self):
        # slate date 09-20 would be long stale, but the game itself starts at START: judged from the start
        self.assertEqual(ticket_status(None, START_TEXT, "2026-09-20", at(1)), TICKET_OPEN)


def row(**over) -> BetRow:
    base = dict(hound_id="setter", date="2026-09-22", game="Texas Rangers at New York Mets", market="h2h",
                selection="New York Mets moneyline", price=116, result=None, start_utc=START_TEXT)
    base.update(over)
    return BetRow(**base)


class ThePayload(unittest.TestCase):
    NOW = at(24 * 27)

    def test_with_status_stamps_each_row(self):
        rows = with_status([row(), row(result="win"), row(start_utc=None, date="2026-10-19")], self.NOW)
        self.assertEqual([r.status for r in rows], ["UNGRADED", "GRADED", "OPEN"])

    def test_a_refusal_is_not_a_ticket_and_keeps_an_empty_status(self):
        refusal = StreamItem(hound_id="setter", date="2026-09-22", refused=True, verdict="refused_thin")
        self.assertEqual(with_status([refusal], self.NOW)[0].status, "")

    def test_the_open_filter_excludes_month_old_tickets_and_the_ungraded_filter_lists_them(self):
        rows = [row(), row(start_utc=None, date="2026-10-19"), row(result="loss")]
        self.assertEqual(len(filter_by_status(rows, "open", self.NOW)), 1)
        self.assertEqual(filter_by_status(rows, "open", self.NOW)[0].date, "2026-10-19")
        self.assertEqual(len(filter_by_status(rows, "ungraded", self.NOW)), 1)
        self.assertEqual(len(filter_by_status(rows, "graded", self.NOW)), 1)
        self.assertEqual(len(filter_by_status(rows, None, self.NOW)), 3)

    def test_the_bets_payload_says_UNGRADED(self):
        page = contract.paginate([row()], 1, 25)
        payload = contract.bets_payload("setter", page, "2026-10-19")
        self.assertEqual(payload["items"][0]["status"], "UNGRADED")   # real clock: the bet is a month old by 2026-10-19+


class TheModelCounts(unittest.TestCase):
    def test_summary_counts_open_and_ungraded_apart(self):
        now = at(24 * 27)
        old = ledgers.Bet(hound_id="setter", date="2026-09-22", start_utc=START_TEXT, bet_id="a")
        today = ledgers.Bet(hound_id="setter", date="2026-10-19", bet_id="b")
        done = ledgers.Bet(hound_id="setter", date="2026-09-22", start_utc=START_TEXT, bet_id="c", result="win",
                           price=100)
        defn = {"id": "setter", "name": "Setter", "tagline": "", "kind": "house", "category": "stats", "style": "",
                "sports": ["mlb"], "markets": ["h2h"], "rule_text": ""}
        # the 'today' bet's slate day (2026-10-19) is after `now` (2026-10-19 00:10Z is START + 27d), still open
        summary = stats.summarize(defn, [old, today, done], {}, "2026-10-19", now=now).summary
        self.assertEqual((summary.open_bets, summary.ungraded_bets), (1, 1))
        self.assertEqual(summary.record.bets, 1)             # an ungraded ticket never enters the record


if __name__ == "__main__":
    unittest.main()
