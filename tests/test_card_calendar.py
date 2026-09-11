"""The calendar's data: a published card counts before it is graded.

WHY
---
`card_ledger.history()` returned settled days only. That is right for a
RECORD -- an ungraded day has no result to put in a tally -- and wrong for a
CALENDAR, which answers "what did you say, and when" before it answers "how
did it go".

Asked for directly: "a true tally, seeable by everyone on a calendar that
people can click and go through and see the verifiable wins." Built from
settled days alone, that calendar is blank on the day a card is published and
fills in only the next morning -- so on the product's first day, and on every
evening before the overnight settle, it reads as though nothing was
published at all.

`pending_days` is additive on purpose: no existing consumer of `days` starts
seeing rows with no result in them.

WHAT IS PINNED
--------------
That the two lists stay DISJOINT and correctly assigned. A date appearing in
both would let a calendar draw a graded day as pending, or worse, show a
result for a day nothing has been graded on -- which on this product is the
one mistake that cannot be walked back.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger


def _card(date, picks):
    return {
        "date": date,
        "picks": picks,
        "filled": len(picks),
        "rule": "rule", "basis": "basis", "disclaimer": "disclaimer",
        "games_on_slate": 5,
    }


def _pick(rank, game_pk, bet="Take Someone at -110"):
    return {
        "rank": rank, "bet": bet, "label": "LEAN", "market": "moneyline",
        "price": -110, "book": "somebook", "books": 8,
        "game_pk": game_pk, "side": "home",
        "away_team": "AAA", "home_team": "HHH",
        "team_name": "Home Team", "opponent_name": "Away Team",
    }


class PublishedDaysAppearBeforeTheyAreGraded(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_a_published_ungraded_day_is_pending_not_missing(self):
        """THE ONE THAT MATTERS. Before this, the calendar had nothing to draw
        on the day a card went up."""
        card_ledger.publish(_card("2026-09-10", [_pick(1, "111")]),
                            path=self.path)
        hist = card_ledger.history(path=self.path)
        self.assertEqual(hist["days"], [])
        self.assertEqual(len(hist["pending_days"]), 1)
        self.assertEqual(hist["pending_days"][0]["date"], "2026-09-10")

    def test_a_pending_day_carries_its_picks_and_its_receipt(self):
        """A pending square is a CLAIM, and a claim with no hash behind it is
        not one this product makes."""
        card_ledger.publish(
            _card("2026-09-10", [_pick(1, "111", "Take Braves to win at -115")]),
            path=self.path)
        day = card_ledger.history(path=self.path)["pending_days"][0]
        self.assertEqual(len(day["picks"]), 1)
        self.assertEqual(day["picks"][0]["bet"], "Take Braves to win at -115")
        self.assertTrue(day["row_hash"])
        self.assertIsNotNone(day["published_utc"])

    def test_a_settled_day_leaves_the_pending_list(self):
        """Otherwise a calendar would draw the same date twice, once with a
        result and once without."""
        card_ledger.publish(_card("2026-09-10", [_pick(1, "111")]),
                            path=self.path)
        card_ledger.settle("2026-09-10",
                           {"111": {"away_score": "1", "home_score": "5"}},
                           path=self.path)
        hist = card_ledger.history(path=self.path)
        self.assertEqual(len(hist["days"]), 1)
        self.assertEqual(hist["pending_days"], [],
                         "a graded date is still being reported as pending")

    def test_the_two_lists_never_share_a_date(self):
        card_ledger.publish(_card("2026-09-09", [_pick(1, "111")]),
                            path=self.path)
        card_ledger.publish(_card("2026-09-10", [_pick(1, "222")]),
                            path=self.path)
        card_ledger.settle("2026-09-09",
                           {"111": {"away_score": "1", "home_score": "5"}},
                           path=self.path)
        hist = card_ledger.history(path=self.path)
        settled = {d["date"] for d in hist["days"]}
        pending = {d["date"] for d in hist["pending_days"]}
        self.assertEqual(settled, {"2026-09-09"})
        self.assertEqual(pending, {"2026-09-10"})
        self.assertEqual(settled & pending, set())

    def test_pending_days_are_newest_first(self):
        for date in ("2026-09-08", "2026-09-10", "2026-09-09"):
            card_ledger.publish(_card(date, [_pick(1, "111")]), path=self.path)
        dates = [d["date"] for d in
                 card_ledger.history(path=self.path)["pending_days"]]
        self.assertEqual(dates, ["2026-09-10", "2026-09-09", "2026-09-08"])

    def test_an_empty_ledger_reports_both_lists_empty(self):
        hist = card_ledger.history(path=self.path)
        self.assertEqual(hist["days"], [])
        self.assertEqual(hist["pending_days"], [])

    def test_the_settled_list_is_unchanged_in_shape(self):
        """`days` is what the record page already reads. Adding a key beside
        it must not alter it."""
        card_ledger.publish(_card("2026-09-10", [_pick(1, "111")]),
                            path=self.path)
        card_ledger.settle("2026-09-10",
                           {"111": {"away_score": "1", "home_score": "5"}},
                           path=self.path)
        day = card_ledger.history(path=self.path)["days"][0]
        for key in ("date", "wins", "losses", "pushes", "voids", "n_staked",
                    "profit_units", "roi_pct", "row_hash",
                    "published_row_hash", "picks"):
            self.assertIn(key, day)


class TheCalendarIsWiredToBothLists(unittest.TestCase):
    """A backend list nothing renders is not a calendar."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "web", "js", "cardrecord.js")
        with open(path, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_the_page_reads_pending_days(self):
        self.assertIn("pending_days", self.source,
                      "the record page ignores published-but-ungraded days, "
                      "so the calendar is blank on the day a card goes up")

    def test_a_graded_day_links_to_its_detail(self):
        """A square a reader cannot click is a picture, not a record."""
        self.assertIn("record-day", self.source)
        self.assertRegex(self.source, r"data-date")

    def test_the_calendar_does_not_parse_dates_through_the_local_timezone(self):
        """`new Date("2026-09-10")` is UTC midnight rendered locally, which in
        the Americas is the day BEFORE. A card drawn on the wrong square is
        worse than no calendar."""
        self.assertNotRegex(
            self.source, r"new Date\(\s*(day|date|dateIso)\s*\)",
            "a date string is being parsed by the Date constructor; use the "
            "ymd() splitter so a reader's timezone cannot move a card to the "
            "wrong day")


if __name__ == "__main__":
    unittest.main()
