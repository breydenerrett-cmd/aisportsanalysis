"""Tests for the multi-book capture path and its downstream consumers.

Four properties, each traced to the audit that motivated the work:

1. Every capture persists EVERY book's h2h quote to the new multi-book store,
   one row per (event, book), from the payload the capture already paid for.
2. The legacy snapshot store stays byte-identical in format -- its existing
   readers (grading, pricepath, the CLI) must not notice anything happened.
3. The multi-book reader emits eventstudy-shaped quotes ({ts, book,
   away_price, home_price}) filtered to one event.
4. The dense runner takes a close-capture pass at T-25, reports games that
   reached first pitch uncovered, settlements carry the closing price they
   were graded against, and a priceless recommendation row says why.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.detect import dossier as dossier_mod
from src.pipeline import dense, ledger, snapshots
from src.providers import odds as odds_provider
from src import cli

FAKE_KEY = "sk-not-real"

NOW = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)


def payload(all_books=True):
    """A normalized fetch payload shaped like odds.fetch_normalized output."""
    event = {
        "event_id": "e1", "commence_time": "2026-08-30T23:05:00Z",
        "away_team": "Houston Astros", "home_team": "New York Yankees",
        "markets": {
            "h2h": {"book": "fanduel", "away_price": 136, "home_price": -162,
                    "last_update": "2026-08-30T14:58:00Z"},
        },
    }
    if all_books:
        event["all_books"] = {"h2h": [
            {"book": "fanduel", "last_update": "2026-08-30T14:58:00Z",
             "away_price": 136, "home_price": -162},
            {"book": "draftkings", "last_update": "2026-08-30T14:57:00Z",
             "away_price": 140, "home_price": -165},
            {"book": "betmgm", "last_update": "2026-08-30T14:50:00Z",
             "away_price": 135, "home_price": -160},
        ]}
    return {"event_count": 1, "events": [event]}


def _capture(tmp, fetched, **kwargs):
    path = Path(tmp) / "snaps.jsonl"
    with mock.patch.object(odds_provider, "fetch_normalized",
                           return_value=fetched):
        result = snapshots.capture(env={"ODDS_API_KEY": FAKE_KEY}, path=path,
                                   **kwargs)
    return path, result


class TestMultibookWrite(unittest.TestCase):
    def test_one_row_per_event_book_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, result = _capture(tmp, payload())
            mb = snapshots.read_multibook(Path(tmp) / "odds_multibook.jsonl")
        self.assertEqual(result["multibook"], 3)
        self.assertEqual([r["book"] for r in mb],
                         ["fanduel", "draftkings", "betmgm"])

    def test_rows_carry_every_required_field(self):
        fixed = datetime(2026, 8, 30, 14, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            _capture(tmp, payload(), now=fixed)
            row = snapshots.read_multibook(
                Path(tmp) / "odds_multibook.jsonl")[1]
        self.assertEqual(row, {
            "observed_utc": "2026-08-30T14:30:00+00:00",
            "event_id": "e1",
            "commence_time": "2026-08-30T23:05:00Z",
            "home_team": "New York Yankees",
            "away_team": "Houston Astros",
            "book": "draftkings",
            "book_last_update": "2026-08-30T14:57:00Z",
            "home_price": -165,
            "away_price": 140,
        })

    def test_multibook_store_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _capture(tmp, payload())
            mb_path = Path(tmp) / "odds_multibook.jsonl"
            first = mb_path.read_text()
            _capture(tmp, payload())
            second = mb_path.read_text()
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.strip().splitlines()), 6)

    def test_half_quoted_book_is_skipped_never_half_recorded(self):
        fetched = payload()
        fetched["events"][0]["all_books"]["h2h"].append(
            {"book": "lame", "away_price": 120, "home_price": None})
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _capture(tmp, fetched)
        self.assertEqual(result["multibook"], 3)

    def test_a_payload_without_all_books_writes_no_multibook_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = _capture(tmp, payload(all_books=False))
            self.assertFalse((Path(tmp) / "odds_multibook.jsonl").exists())
        self.assertEqual(result["multibook"], 0)

    def test_capture_makes_exactly_one_api_fetch(self):
        # The multi-book store must come from the SAME response -- zero extra
        # credits. One fetch_normalized call, no matter how many stores.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            with mock.patch.object(odds_provider, "fetch_normalized",
                                   return_value=payload()) as fetch:
                snapshots.capture(env={"ODDS_API_KEY": FAKE_KEY}, path=path)
        self.assertEqual(fetch.call_count, 1)


class TestLegacyStoreUntouched(unittest.TestCase):
    def test_legacy_rows_are_byte_identical_with_and_without_all_books(self):
        # The exact serialized line an old reader sees must not change when the
        # payload carries the multi-book board.
        with tempfile.TemporaryDirectory() as with_dir, \
                tempfile.TemporaryDirectory() as without_dir:
            fixed = datetime(2026, 8, 30, 14, 30, tzinfo=timezone.utc)
            with_path, _ = _capture(with_dir, payload(), now=fixed)
            without_path, _ = _capture(without_dir, payload(all_books=False),
                                       now=fixed)
            self.assertEqual(with_path.read_text(), without_path.read_text())

    def test_legacy_row_keys_are_the_historical_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = _capture(tmp, payload())
            row = snapshots.read(path)[0]
        self.assertEqual(set(row), {
            "observed_utc", "event_id", "commence_time", "away_team",
            "home_team", "market", "book", "prices", "book_last_update"})

    def test_old_readers_still_group_and_close_the_legacy_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixed = datetime(2026, 8, 30, 14, 30, tzinfo=timezone.utc)
            path, _ = _capture(tmp, payload(), now=fixed)
            grouped = snapshots.group_by_game(snapshots.read(path))
        key = ("Houston Astros", "New York Yankees", "2026-08-30")
        self.assertIn(key, grouped)
        self.assertIsNotNone(snapshots.closing_observation(grouped[key]))


class TestEventstudyReader(unittest.TestCase):
    def test_quotes_are_eventstudy_shaped_and_filtered_by_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetched = payload()
            fetched["events"].append({
                "event_id": "e2", "commence_time": "2026-08-30T20:10:00Z",
                "away_team": "A", "home_team": "B", "markets": {},
                "all_books": {"h2h": [
                    {"book": "fanduel", "last_update": "x",
                     "away_price": 100, "home_price": -120}]},
            })
            fixed = datetime(2026, 8, 30, 14, 30, tzinfo=timezone.utc)
            _capture(tmp, fetched, now=fixed)
            quotes = snapshots.multibook_quotes(
                event_id="e1", path=Path(tmp) / "odds_multibook.jsonl")
        self.assertEqual(len(quotes), 3)
        for quote in quotes:
            self.assertEqual(set(quote),
                             {"ts", "book", "away_price", "home_price"})
        self.assertEqual(quotes[0]["ts"], "2026-08-30T14:30:00+00:00")
        self.assertEqual({q["book"] for q in quotes},
                         {"fanduel", "draftkings", "betmgm"})

    def test_quotes_sort_oldest_first_across_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            later = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)
            earlier = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
            _capture(tmp, payload(), now=later)
            _capture(tmp, payload(), now=earlier)
            quotes = snapshots.multibook_quotes(
                event_id="e1", path=Path(tmp) / "odds_multibook.jsonl")
        self.assertEqual(quotes[0]["ts"], "2026-08-30T14:00:00+00:00")
        self.assertEqual(quotes[-1]["ts"], "2026-08-30T15:00:00+00:00")

    def test_a_filterless_call_is_refused_not_a_full_dump(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.multibook_quotes(rows=[])

    def test_measured_by_eventstudy_end_to_end(self):
        # The reader's output must be directly consumable by the V3 core.
        from src.research import eventstudy
        rows = []
        base = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        for minutes, away, home in ((0, 120, -140), (15, 120, -140),
                                    (30, 100, -120), (45, 100, -120)):
            ts = (base + timedelta(minutes=minutes)).isoformat()
            for book in ("a", "b", "c", "d", "e", "f"):
                rows.append({"observed_utc": ts, "event_id": "e1",
                             "commence_time": "2026-08-30T23:05:00Z",
                             "home_team": "H", "away_team": "A", "book": book,
                             "book_last_update": ts,
                             "home_price": home, "away_price": away})
        quotes = snapshots.multibook_quotes(event_id="e1", rows=rows)
        result = eventstudy.measure(
            {"ts": (base + timedelta(minutes=20)).isoformat()}, quotes)
        self.assertIsNone(result["excluded"])
        self.assertEqual(result["books_pre"], 6)
        self.assertEqual(result["books_moved"], 6)


class TestClosePassAndMissedWindows(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.real_quota = dense.odds_provider.quota
        self.real_status = dense.odds_provider.status
        self.real_capture = dense.snapshots.capture
        self.real_read = dense.snapshots.read
        self.real_upcoming = dense._upcoming
        dense.odds_provider.status = lambda env=None: {"configured": True}
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense.snapshots.capture = self._capture
        dense.snapshots.read = lambda *a, **k: []

    def tearDown(self):
        dense.odds_provider.quota = self.real_quota
        dense.odds_provider.status = self.real_status
        dense.snapshots.capture = self.real_capture
        dense.snapshots.read = self.real_read
        dense._upcoming = self.real_upcoming

    def _capture(self, env=None):
        self.calls.append("capture")
        return {"captured": 30, "events": 15, "configured": True}

    def test_close_pass_fires_when_a_game_is_inside_t_minus_25(self):
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:20:00Z"}])
        result = dense.run(captures=1, now=NOW, sleep=None)
        self.assertIsNotNone(result["close_capture"])
        self.assertEqual(result["close_capture"]["captured"], 30)
        # One loop capture plus the close pass.
        self.assertEqual(len(self.calls), 2)

    def test_close_pass_fires_even_when_the_loop_found_no_window_game(self):
        # A game 20 minutes out is inside T-25 regardless of what the spaced
        # loop thought; the close pass is its own check.
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:20:00Z"}])
        result = dense.run(captures=1, window_minutes=10, now=NOW, sleep=None)
        self.assertEqual(result["stopped_early"], "no game inside the window")
        self.assertIsNotNone(result["close_capture"])
        self.assertEqual(len(self.calls), 1)

    def test_no_close_pass_when_first_pitch_is_far_away(self):
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T17:00:00Z"}])
        result = dense.run(captures=1, now=NOW, sleep=None)
        self.assertIsNone(result["close_capture"])
        self.assertEqual(len(self.calls), 1)

    def test_close_pass_respects_the_credit_floor(self):
        # The floor check precedes EVERY spend, the close pass included.
        dense.odds_provider.quota = lambda env=None: {"remaining": 100}
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:20:00Z"}])
        result = dense.run(captures=1, now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "credit floor")
        self.assertEqual(self.calls, [])

    def test_close_pass_rechecks_the_floor_after_the_loop_spent(self):
        balances = iter([{"remaining": 50000}, {"remaining": 100}])
        dense.odds_provider.quota = lambda env=None: next(balances)
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:20:00Z"}])
        result = dense.run(captures=1, now=NOW, sleep=None)
        self.assertEqual(result["close_capture"]["skipped"], "credit floor")
        self.assertEqual(len(self.calls), 1)

    def test_a_game_that_started_uncovered_is_reported_as_missed(self):
        # Clock: run starts 15:00, loop capture at 15:00, run ends 16:00.
        # The 15:45 game reached first pitch with no capture inside its
        # final 30 minutes (15:15-15:45).
        ticks = iter([NOW, NOW, NOW + timedelta(hours=1)])
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:45:00Z"}])
        result = dense.run(captures=1, now=lambda: next(ticks), sleep=None)
        self.assertEqual(len(result["missed_windows"]), 1)
        self.assertEqual(result["missed_windows"][0]["commence_time"],
                         "2026-08-30T15:45:00Z")
        self.assertIn("last 30 minutes", result["missed_windows"][0]["reason"])

    def test_a_covered_game_is_not_reported(self):
        # Same shape, but the loop capture at 15:20 falls inside the 15:45
        # game's final half hour.
        ticks = iter([NOW, NOW + timedelta(minutes=20),
                      NOW + timedelta(hours=1)])
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:45:00Z"}])
        result = dense.run(captures=1, now=lambda: next(ticks), sleep=None)
        self.assertEqual(result["missed_windows"], [])

    def test_a_capture_from_an_earlier_run_counts_as_coverage(self):
        ticks = iter([NOW, NOW, NOW + timedelta(hours=1)])
        dense.snapshots.read = lambda *a, **k: [
            {"observed_utc": "2026-08-30T15:30:00+00:00"}]
        dense._upcoming = (lambda now=None, timeout=20:
                           [{"commence_time": "2026-08-30T15:45:00Z"}])
        result = dense.run(captures=1, now=lambda: next(ticks), sleep=None)
        self.assertEqual(result["missed_windows"], [])


class TestSettlementClosing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def _rec(self):
        return {"away_team": "Houston Astros", "home_team": "New York Yankees",
                "commence_time": "2026-08-30T23:05:00Z"}

    def _series(self, observed="2026-08-30T22:50:00+00:00"):
        return {("Houston Astros", "New York Yankees", "2026-08-30"): [{
            "observed_utc": observed, "market": "h2h", "book": "fanduel",
            "commence_time": "2026-08-30T23:05:00Z",
            "book_last_update": observed,
            "prices": {"home_price": -170, "away_price": 145},
        }]}

    def test_the_close_the_grade_used_lands_on_the_settlement_row(self):
        closing, reason = cli._settlement_closing(self._rec(), self._series())
        self.assertIsNone(reason)
        self.assertEqual(closing["prices"]["home_price"], -170)
        self.assertEqual(closing["book"], "fanduel")
        ledger.settle(1, {"winner": "NYY"}, closing=closing,
                      closing_reason=reason, path=self.path)
        row = ledger.settlements(path=self.path)[1]
        self.assertEqual(row["closing"]["prices"]["away_price"], 145)
        self.assertNotIn("closing_reason", row)

    def test_the_settlement_row_carries_how_stale_the_close_was(self):
        series = self._series()
        key = ("Houston Astros", "New York Yankees", "2026-08-30")
        series[key][0]["book_last_update"] = "2026-08-30T21:40:00+00:00"
        closing, reason = cli._settlement_closing(self._rec(), series)
        self.assertTrue(closing["book_stale"])
        self.assertEqual(closing["book_stale_seconds"], 4200.0)
        ledger.settle(1, {"winner": "NYY"}, closing=closing,
                      closing_reason=reason, path=self.path)
        row = ledger.settlements(path=self.path)[1]
        self.assertTrue(row["closing"]["book_stale"])

    def test_a_close_with_no_book_stamp_reports_unknown_staleness(self):
        series = self._series()
        key = ("Houston Astros", "New York Yankees", "2026-08-30")
        series[key][0]["book_last_update"] = None
        closing, _ = cli._settlement_closing(self._rec(), series)
        self.assertIsNone(closing["book_stale_seconds"])
        self.assertFalse(closing["book_stale"])

    def test_settlement_rows_written_before_staleness_existed_still_read(self):
        # Old evidence is never rewritten, so readers meet closings with no
        # staleness fields; missing must read as "unknown", not crash.
        legacy = {"market": "h2h", "book": "fanduel",
                  "observed_utc": "2026-08-30T22:50:00+00:00",
                  "book_last_update": "2026-08-30T22:49:00+00:00",
                  "prices": {"home_price": -170, "away_price": 145}}
        ledger.settle(1, {"winner": "NYY"}, closing=legacy, path=self.path)
        row = ledger.settlements(path=self.path)[1]["closing"]
        self.assertNotIn("book_stale", row)
        self.assertIsNone(row.get("book_stale_seconds"))
        self.assertEqual(row["prices"]["home_price"], -170)

    def test_no_snapshots_at_all_yields_null_close_with_a_reason(self):
        closing, reason = cli._settlement_closing(self._rec(), {})
        self.assertIsNone(closing)
        self.assertEqual(reason, "no snapshots recorded for this game")

    def test_only_post_pitch_snapshots_yield_null_close_with_a_reason(self):
        series = self._series(observed="2026-08-30T23:30:00+00:00")
        closing, reason = cli._settlement_closing(self._rec(), series)
        self.assertIsNone(closing)
        self.assertEqual(reason, "no snapshot observed before first pitch")

    def test_a_null_close_is_never_silent_on_the_row(self):
        ledger.settle(1, {"winner": "NYY"}, closing=None,
                      closing_reason="no snapshots recorded for this game",
                      path=self.path)
        row = ledger.settlements(path=self.path)[1]
        self.assertIsNone(row["closing"])
        self.assertEqual(row["closing_reason"],
                         "no snapshots recorded for this game")


class TestRecommendationPriceReason(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def _game(self, market=None, gaps=None):
        d = dossier_mod.Dossier(
            {"game_pk": 1, "away_team": "BOS", "home_team": "NYY",
             "date": "2026-08-30", "start_time_utc": "2026-08-30T23:05:00Z"})
        if market is not None:
            d.add("market", market)
        for name, reason in (gaps or {}).items():
            d.miss(name, reason)
        return {"dossier": d, "findings": [], "verdict": "no_play",
                "side": None, "market": None, "summary": "x"}

    def _record(self, game):
        ledger.record_slate(
            {"date": "2026-08-30", "games": [game], "notes": []},
            path=self.path)
        return ledger.recommendations(path=self.path)[0]

    def test_a_priceless_row_says_why(self):
        entry = self._record(self._game(
            gaps={"market": "no prices on the board for this game"}))
        self.assertEqual(entry["prices"], {})
        self.assertEqual(entry["price_reason"],
                         "no prices on the board for this game")

    def test_an_empty_market_section_still_gets_a_reason(self):
        entry = self._record(self._game(market={"markets": {},
                                                "all_books": {}}))
        self.assertIn("price_reason", entry)

    def test_a_priced_row_carries_no_reason_field(self):
        market = {"markets": {"h2h": {"book": "fanduel", "away_price": 120,
                                      "home_price": -140}},
                  "all_books": {"h2h": [{"book": "fanduel", "away_price": 120,
                                         "home_price": -140}]}}
        entry = self._record(self._game(market=market))
        self.assertNotIn("price_reason", entry)


if __name__ == "__main__":
    unittest.main()


class TestPregameFilter(unittest.TestCase):
    """The store keeps in-play rows; `is_pregame` is the one place that says so.

    Quantified on the live store 2026-08-31/09-01: 592 of 5,803 rows observed
    after their own commence_time, across 10 of 26 events, up to 2h50m late.
    Capture writes them because a capture is one bulk call for the whole board
    and the feed keeps listing a started game; they are append-only evidence
    and stay. Only consumers that mean "the pre-game market" filter.
    """

    def row(self, observed, commence="2026-08-31T23:10:00Z"):
        return {"observed_utc": observed, "commence_time": commence,
                "book": "fanduel", "home_price": -110, "away_price": -110}

    def test_before_first_pitch_is_pregame(self):
        self.assertTrue(snapshots.is_pregame(self.row("2026-08-31T23:09:59Z")))

    def test_at_and_after_first_pitch_is_not(self):
        self.assertFalse(snapshots.is_pregame(self.row("2026-08-31T23:10:00Z")))
        self.assertFalse(snapshots.is_pregame(self.row("2026-09-01T01:00:00Z")))

    def test_a_row_that_cannot_be_shown_pregame_is_not_served_as_one(self):
        for row in ({"observed_utc": "2026-08-31T22:00:00Z"},
                    {"commence_time": "2026-08-31T23:10:00Z"},
                    self.row("not-a-timestamp"),
                    self.row("2026-08-31T22:00:00Z", commence="soon")):
            self.assertFalse(snapshots.is_pregame(row), row)

    def test_the_rule_is_the_closing_lines_rule(self):
        """Same constant, so the two definitions cannot drift apart."""
        series = [self.row("2026-08-31T22:00:00Z"),
                  self.row("2026-08-31T23:47:00Z")]
        close = snapshots.closing_observation(series)
        kept = snapshots.pregame_rows(series)
        self.assertEqual(len(kept), 1)
        self.assertEqual(close["observed_utc"], kept[-1]["observed_utc"])

    def test_pregame_rows_filters_and_never_rewrites(self):
        series = [self.row("2026-08-31T22:00:00Z"),
                  self.row("2026-09-01T01:00:00Z")]
        kept = snapshots.pregame_rows(series)
        self.assertEqual(kept, [series[0]])
        self.assertIs(kept[0], series[0])
        self.assertEqual(len(series), 2)

    def test_quotes_are_raw_by_default_and_pregame_on_request(self):
        rows = [dict(self.row("2026-08-31T22:00:00Z"), event_id="e1"),
                dict(self.row("2026-08-31T23:47:00Z"), event_id="e1")]
        self.assertEqual(
            len(snapshots.multibook_quotes(event_id="e1", rows=rows)), 2)
        pregame = snapshots.multibook_quotes(event_id="e1", rows=rows,
                                             pregame_only=True)
        self.assertEqual([q["ts"] for q in pregame], ["2026-08-31T22:00:00Z"])
