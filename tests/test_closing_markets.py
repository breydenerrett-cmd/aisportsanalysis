"""Tests for L17: market-aware closing identification beyond h2h.

WHAT THIS PROVES
-----------------
1. `snapshots.closing_observation` and `snapshots.group_by_game` are
   UNCHANGED by this lane -- their h2h default behaves byte-for-byte as it
   did before (see TestH2HDefaultUnchanged).
2. `snapshots.market_series_index` / `market_closing_observation` extend the
   SAME PIT rule -- last observation strictly before first pitch -- to
   spreads and totals (captured in odds_snapshots.jsonl, same row shape as
   h2h) and to first_five (captured in f5_close.jsonl, a DIFFERENT row shape
   with no `prices` wrapper and the odds feed's own market key).
3. `grading.ledger_closing_coverage`'s per-market table is exercised via
   tests/test_closing_backfill.py's TestMarketCoverage; this file focuses on
   the snapshots-layer primitives that table is built on.
"""

import unittest

from src.pipeline import snapshots
from src.pipeline.snapshots import SnapshotError


def h2h_row(observed, away="Houston Astros", home="New York Yankees",
           commence="2026-08-27T23:05:00Z", market="h2h",
           home_price=-130, away_price=110):
    """A row shaped exactly like `snapshots.capture` writes odds_snapshots.jsonl
    for h2h/spreads/totals: prices nested under `prices`."""
    return {
        "observed_utc": observed, "event_id": "e1", "commence_time": commence,
        "away_team": away, "home_team": home, "market": market,
        "book": "fanduel", "book_last_update": observed,
        "prices": {"home_price": home_price, "away_price": away_price},
    }


def f5_row(observed, away="Houston Astros", home="New York Yankees",
          commence="2026-08-27T23:05:00Z",
          home_price=-140, away_price=120, book="fanduel"):
    """A row shaped exactly like `pipeline.dense._f5_close_pass` writes
    f5_close.jsonl: home_price/away_price are TOP-LEVEL fields, not nested
    under `prices`, and `market` is the odds feed's own key."""
    return {
        "observed_utc": observed, "event_id": "e1", "commence_time": commence,
        "away_team": away, "home_team": home, "market": "h2h_1st_5_innings",
        "book": book, "book_last_update": observed,
        "home_price": home_price, "away_price": away_price,
    }


class TestH2HDefaultUnchanged(unittest.TestCase):
    """This lane must not change one byte of h2h's existing behaviour."""

    def test_group_by_game_default_still_filters_to_h2h(self):
        rows = [h2h_row("2026-08-27T12:00:00+00:00", market="h2h"),
               h2h_row("2026-08-27T12:00:00+00:00", market="totals")]
        self.assertEqual(len(snapshots.group_by_game(rows)), 1)

    def test_closing_observation_still_picks_the_last_pregame_row(self):
        series = [
            h2h_row("2026-08-27T12:00:00+00:00", home_price=-130),
            h2h_row("2026-08-27T22:55:00+00:00", home_price=-150),
            h2h_row("2026-08-27T23:30:00+00:00", home_price=-400),  # post first pitch
        ]
        closing = snapshots.closing_observation(series)
        self.assertEqual(closing["prices"]["home_price"], -150)

    def test_market_series_index_h2h_matches_group_by_game_default(self):
        # The new entry point must not diverge from the old one for the
        # market both already agreed on.
        rows = [h2h_row("2026-08-27T12:00:00+00:00", market="h2h"),
               h2h_row("2026-08-27T12:00:00+00:00", market="spreads")]
        via_new = snapshots.market_series_index(rows, market="h2h")
        via_old = snapshots.group_by_game(rows)  # default market="h2h"
        self.assertEqual(via_new, via_old)


class TestMarketSeriesIndex(unittest.TestCase):
    def test_unknown_market_raises_rather_than_returning_empty(self):
        with self.assertRaises(SnapshotError):
            snapshots.market_series_index([], market="player_props")

    def test_spreads_and_totals_index_separately_from_h2h(self):
        rows = [h2h_row("2026-08-27T12:00:00+00:00", market="h2h"),
               h2h_row("2026-08-27T12:00:00+00:00", market="spreads"),
               h2h_row("2026-08-27T12:00:00+00:00", market="totals")]
        self.assertEqual(len(snapshots.market_series_index(rows, market="h2h")), 1)
        self.assertEqual(len(snapshots.market_series_index(rows, market="spreads")), 1)
        self.assertEqual(len(snapshots.market_series_index(rows, market="totals")), 1)

    def test_first_five_reads_the_feeds_own_market_key(self):
        # first_five is this project's name; the row's own `market` field
        # says h2h_1st_5_innings. A caller who only knows the project name
        # must still find it.
        rows = [f5_row("2026-08-27T22:50:00+00:00")]
        index = snapshots.market_series_index(rows, market="first_five")
        self.assertEqual(len(index), 1)


class TestMarketClosingObservation(unittest.TestCase):
    """Same PIT discipline as `closing_observation`, extended to spreads,
    totals, and first_five -- via whichever store's rows are handed in."""

    def test_spreads_closing_comes_from_the_last_pregame_row(self):
        rows = [h2h_row("2026-08-27T12:00:00+00:00", market="spreads",
                        home_price=-110), h2h_row("2026-08-27T22:55:00+00:00",
                        market="spreads", home_price=-120)]
        index = snapshots.market_series_index(rows, market="spreads")
        observation, reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        self.assertIsNone(reason)
        self.assertEqual(observation["prices"]["home_price"], -120)

    def test_totals_closing_comes_from_the_last_pregame_row(self):
        row = h2h_row("2026-08-27T22:55:00+00:00", market="totals")
        row["prices"] = {"total": 8.5, "over_price": -110, "under_price": -110}
        index = snapshots.market_series_index([row], market="totals")
        observation, reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        self.assertIsNone(reason)
        self.assertEqual(observation["prices"]["total"], 8.5)

    def test_first_five_closing_reads_top_level_prices_not_nested(self):
        rows = [f5_row("2026-08-27T22:50:00+00:00", home_price=-140, away_price=120)]
        index = snapshots.market_series_index(rows, market="first_five")
        observation, reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        self.assertIsNone(reason)
        self.assertEqual(observation["home_price"], -140)
        self.assertEqual(observation["away_price"], 120)

    def test_first_five_pit_discipline_excludes_post_first_pitch_rows(self):
        # The store's own design (one capture near the close window) makes
        # this rare in practice, but the rule must hold generically: an
        # observation at or after first pitch is never a close, for
        # first_five exactly as for h2h.
        rows = [f5_row("2026-08-27T23:30:00+00:00")]  # after 23:05 first pitch
        index = snapshots.market_series_index(rows, market="first_five")
        observation, reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        self.assertIsNone(observation)
        self.assertEqual(reason, "no snapshot observed before first pitch")

    def test_not_captured_when_the_game_has_no_rows_at_all(self):
        index = snapshots.market_series_index([], market="first_five")
        observation, reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        self.assertIsNone(observation)
        self.assertEqual(reason, "not_captured")

    def test_not_captured_is_distinct_from_no_snapshot_before_first_pitch(self):
        # Two different gaps must never collapse onto the same reason: one
        # game has rows that arrived too late, the other has none at all.
        late_only = [h2h_row("2026-08-27T23:30:00+00:00", market="h2h")]
        index = snapshots.market_series_index(late_only, market="h2h")

        _, late_reason = snapshots.market_closing_observation(
            index, "Houston Astros", "New York Yankees", "2026-08-27T23:05:00Z")
        _, absent_reason = snapshots.market_closing_observation(
            index, "Colorado Rockies", "Washington Nationals", "2026-08-27T23:05:00Z")

        self.assertEqual(late_reason, "no snapshot observed before first pitch")
        self.assertEqual(absent_reason, "not_captured")
        self.assertNotEqual(late_reason, absent_reason)

    def test_team_name_canonicalization_still_applies(self):
        # market_closing_observation is built on game_key, which
        # canonicalizes club names on both sides of the join (commit
        # 65f499a) -- this must carry through for every market, not just h2h.
        rows = [f5_row("2026-08-27T22:50:00+00:00",
                       away="Arizona Diamondbacks", home="San Francisco Giants")]
        index = snapshots.market_series_index(rows, market="first_five")
        observation, reason = snapshots.market_closing_observation(
            index, "AZ", "SF", "2026-08-27T23:05:00Z")
        self.assertIsNone(reason)
        self.assertIsNotNone(observation)


if __name__ == "__main__":
    unittest.main()
