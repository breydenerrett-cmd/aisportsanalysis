"""The extra numbers the model leaderboard reads (2026-10-19): last ten results, the typical price taken, the
share of bets that beat the close, a ticket's book count, and the open/graded filter on a model's tickets.

All additive: the record, the verdict and the units are not touched. The expected values are worked by hand
in the comments. Everything here is synthetic.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.hounds import contract, stats
from src.hounds.contract import filter_by_status
from tests.test_hounds_voice import mkbet


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)    # a fixed clock: whether a ticket is stale is time-dependent


def form_of(bets, as_of="2026-10-18"):
    graded = sorted((b for b in bets if b.graded), key=lambda b: (b.date, b.decision_utc or ""))
    return stats.compute_form(graded, True, as_of, {})


class LastTenResults(unittest.TestCase):
    def test_the_last_ten_decided_results_oldest_first(self):
        results = ["win", "loss", "win", "win", "push", "loss", "loss", "win", "win", "loss", "win", "win"]
        bets = [mkbet(f"2026-10-{i + 1:02d}", r) for i, r in enumerate(results)]
        last10 = form_of(bets)["last10"]
        self.assertEqual(len(last10), 10)
        self.assertEqual(last10, ["W", "W", "P", "L", "L", "W", "W", "L", "W", "W"])

    def test_a_young_model_has_a_short_list_not_a_padded_one(self):
        self.assertEqual(form_of([mkbet("2026-10-10", "win"), mkbet("2026-10-11", "loss")])["last10"], ["W", "L"])

    def test_a_void_bet_is_not_a_result(self):
        self.assertEqual(form_of([mkbet("2026-10-10", "void"), mkbet("2026-10-11", "win")])["last10"], ["W"])


class TypicalPriceTaken(unittest.TestCase):
    def test_even_prices_average_to_themselves(self):
        # -110 = decimal 1.9091 each; the mean converts back to -110.
        self.assertEqual(form_of([mkbet("2026-10-10", "win", price=-110),
                                  mkbet("2026-10-11", "loss", price=-110)])["avg_price"], -110)

    def test_a_dog_and_a_favourite_average_in_decimal_not_in_american(self):
        # +150 = 2.5, -150 = 1.6667: mean 2.0833 -> +108, not the American mean of 0.
        got = form_of([mkbet("2026-10-10", "win", price=150), mkbet("2026-10-11", "loss", price=-150)])["avg_price"]
        self.assertEqual(got, 108)

    def test_no_priced_bet_is_none(self):
        self.assertIsNone(stats.average_price_taken([]))


class ShareOfBetsThatBeatTheClose(unittest.TestCase):
    def test_counts_strictly_positive_and_reports_n(self):
        got = stats.clv_beat_share([("d", 1.2), ("d", -0.4), ("d", 0.0), ("d", 0.3)])
        self.assertEqual((got["n"], got["beat"], got["pct"]), (4, 2, 0.5))

    def test_nothing_measurable_is_none_not_zero(self):
        self.assertIsNone(stats.clv_beat_share([]))


class TicketsCarryTheirBookCount(unittest.TestCase):
    def test_book_count_rides_on_the_ticket_and_is_none_when_unknown(self):
        known = stats.bet_row(mkbet("2026-10-10", "win", book_count=7), None)
        unknown = stats.bet_row(mkbet("2026-10-10", "win"), None)
        self.assertEqual(known.book_count, 7)
        self.assertIsNone(unknown.book_count)
        self.assertIn("book_count", contract.to_json(unknown))


class OpenTicketCount(unittest.TestCase):
    DEFN = {"id": "h", "name": "H", "tagline": "", "kind": "house", "category": "stats", "style": "",
            "sports": ["mlb"], "markets": ["h2h"], "rule_text": ""}

    def test_a_model_with_only_open_tickets_counts_them_and_has_no_graded_record(self):
        bets = [mkbet("2026-10-18", None), mkbet("2026-10-18", None)]
        summary = stats.summarize(self.DEFN, bets, {}, "2026-10-18", now=NOW).summary
        self.assertEqual(summary.open_bets, 2)
        self.assertEqual(summary.record.bets, 0)

    def test_graded_tickets_are_not_open_and_replay_never_counts(self):
        bets = [mkbet("2026-10-17", "win"), mkbet("2026-10-18", None), mkbet("2026-10-18", None, segment="replay")]
        summary = stats.summarize(self.DEFN, bets, {}, "2026-10-18", now=NOW).summary
        self.assertEqual((summary.open_bets, summary.record.bets), (1, 1))


class OpenAndGradedFilter(unittest.TestCase):
    def test_open_is_not_yet_graded_and_graded_is_the_rest(self):
        rows = [stats.bet_row(mkbet("2026-10-10", r), None) for r in ("win", None, "loss", None)]
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)      # the slate day itself: not stale
        self.assertEqual(len(filter_by_status(rows, "open", now)), 2)
        self.assertEqual(len(filter_by_status(rows, "graded", now)), 2)
        self.assertEqual(len(filter_by_status(rows, None, now)), 4)
        self.assertTrue(all(r.result is None for r in filter_by_status(rows, "open", now)))


if __name__ == "__main__":
    unittest.main()
