"""Tests for the Research Family V2 market-structure harness."""

import datetime as dt
import unittest

from src.research import m1_overreaction, m2_staleness, m5_devig, pricepath


def _quote(book, minutes_out, away_price, home_price, start=None):
    start = start or dt.datetime(2024, 5, 1, 23, 0, tzinfo=dt.timezone.utc)
    return {
        "book": book,
        "snapshot_at": start - dt.timedelta(minutes=minutes_out),
        "gap_minutes": float(minutes_out),
        "away_price": away_price,
        "home_price": home_price,
    }


def _path(quotes, home_won=True, event_id="e1"):
    return {
        "event_id": event_id,
        "commence_time": dt.datetime(2024, 5, 1, 23, 0, tzinfo=dt.timezone.utc),
        "away_team": "NYY",
        "home_team": "BOS",
        "game_pk": "1",
        "date": "2024-05-01",
        "home_won": home_won,
        "total_runs": 8,
        "quotes": sorted(quotes, key=lambda q: q["snapshot_at"]),
    }


class QuoteSelectionTests(unittest.TestCase):
    def test_quote_at_takes_the_latest_quote_still_far_enough_out(self):
        path = _path([_quote("dk", 600, 100, -120),
                      _quote("dk", 200, 105, -125),
                      _quote("dk", 30, 110, -130)])
        picked = pricepath.quote_at(path, 90)
        self.assertEqual(picked[1][0]["gap_minutes"], 200.0)

    def test_quote_at_never_returns_a_quote_inside_the_lead(self):
        path = _path([_quote("dk", 30, 110, -130)])
        self.assertIsNone(pricepath.quote_at(path, 90))

    def test_latest_quote_is_the_last_before_first_pitch(self):
        path = _path([_quote("dk", 600, 100, -120), _quote("dk", 30, 110, -130)])
        self.assertEqual(pricepath.latest_quote(path)[1][0]["gap_minutes"], 30.0)

    def test_snapshots_group_every_book_quoting_at_one_moment(self):
        path = _path([_quote("dk", 200, 100, -120), _quote("fd", 200, 102, -122)])
        grouped = pricepath.snapshots(path)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(grouped[0][1]), 2)

    def test_by_book_keeps_each_books_path_in_time_order(self):
        path = _path([_quote("dk", 30, 110, -130), _quote("dk", 600, 100, -120)])
        gaps = [q["gap_minutes"] for q in pricepath.by_book(path)["dk"]]
        self.assertEqual(gaps, [600.0, 30.0])


class DevigTests(unittest.TestCase):
    def test_consensus_averages_across_books(self):
        quotes = [_quote("dk", 200, 100, -120), _quote("fd", 200, 100, -120)]
        value = m5_devig.consensus(quotes, "proportional")
        single = m5_devig.consensus([quotes[0]], "proportional")
        self.assertAlmostEqual(value, single, places=9)

    def test_a_row_is_dropped_unless_every_method_produces_a_number(self):
        # All four methods handle ordinary prices, so a normal path yields a row.
        path = _path([_quote("dk", 400, 100, -120)])
        self.assertEqual(len(m5_devig.rows([path], 360)), 1)

    def test_every_method_is_scored_on_the_same_games(self):
        paths = [_path([_quote("dk", 400, 100, -120)], home_won=True, event_id="a"),
                 _path([_quote("dk", 400, -150, 130)], home_won=False, event_id="b")]
        result = m5_devig.evaluate(paths)
        self.assertEqual(result["n"], 2)
        self.assertEqual(set(result["overall"]), set(m5_devig.METHODS))

    def test_shin_matches_additive_on_two_way_markets(self):
        # A mathematical identity for two outcomes, not a bug. Recorded as a
        # test so a future change to either solver has to be deliberate.
        quotes = [_quote("dk", 200, 150, -170)]
        self.assertAlmostEqual(m5_devig.consensus(quotes, "shin"),
                               m5_devig.consensus(quotes, "additive"), places=10)


class StalenessTests(unittest.TestCase):
    def test_a_game_with_one_snapshot_contributes_nothing(self):
        path = _path([_quote("dk", 400, 100, -120)])
        self.assertEqual(m2_staleness.rows([path]), [])

    def test_gap_caps_exclude_a_stale_early_quote(self):
        path = _path([_quote("dk", 900, 100, -120), _quote("dk", 30, 110, -130)])
        self.assertEqual(len(m2_staleness.rows([path])), 1)
        self.assertEqual(m2_staleness.rows([path], max_early_gap=240), [])

    def test_afternoon_start_is_classified_as_a_day_game(self):
        # 19:00 UTC at Fenway is early afternoon local.
        hour = m2_staleness._local_hour(
            dt.datetime(2024, 5, 4, 19, 0, tzinfo=dt.timezone.utc), "BOS")
        self.assertLess(hour, m2_staleness.DAY_GAME_BEFORE_HOUR)


class OverreactionTests(unittest.TestCase):
    def test_changes_are_measured_within_one_book(self):
        # Two books, two quotes each: no book has the three quotes a pair needs.
        path = _path([_quote("dk", 600, 100, -120), _quote("dk", 300, 105, -125),
                      _quote("fd", 600, 100, -120), _quote("fd", 300, 105, -125)])
        self.assertEqual(m1_overreaction.changes([path]), [])

    def test_three_quotes_from_one_book_make_exactly_one_pair(self):
        path = _path([_quote("dk", 600, 100, -120),
                      _quote("dk", 300, 120, -140),
                      _quote("dk", 60, 105, -125)])
        rows = m1_overreaction.changes([path])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["book"], "dk")

    def test_a_move_toward_home_is_faded_by_backing_away(self):
        path = _path([_quote("dk", 600, 100, -120),
                      _quote("dk", 300, 140, -160),
                      _quote("dk", 60, 145, -165)], home_won=True)
        rows = m1_overreaction.changes([path])
        self.assertGreater(rows[0]["previous_delta"], 0)
        result = m1_overreaction.fade(rows, 0.001)
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["share_home"], 0.0)
        self.assertEqual(result["hit_rate"], 0.0)

    def test_a_move_below_the_threshold_does_not_trade(self):
        path = _path([_quote("dk", 600, 100, -120),
                      _quote("dk", 300, 101, -121),
                      _quote("dk", 60, 102, -122)])
        rows = m1_overreaction.changes([path])
        self.assertEqual(m1_overreaction.fade(rows, 0.5)["n"], 0)


if __name__ == "__main__":
    unittest.main()
