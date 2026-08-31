"""The F5 close pass: bounded per-event spend, honest failure reporting."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import dense

NOW = dt.datetime(2026, 8, 31, 22, 0, tzinfo=dt.timezone.utc)


def _event(identifier, minutes_out):
    commence = NOW + dt.timedelta(minutes=minutes_out)
    return {"id": identifier,
            "commence_time": commence.isoformat().replace("+00:00", "Z"),
            "home_team": "New York Mets", "away_team": "Cincinnati Reds"}


def _payload(identifier, books=("fanduel", "draftkings")):
    return {
        "id": identifier, "commence_time": "2026-08-31T22:10:00Z",
        "home_team": "New York Mets", "away_team": "Cincinnati Reds",
        "bookmakers": [{
            "key": book,
            "markets": [{"key": dense.F5_CLOSE_MARKET,
                         "last_update": "2026-08-31T21:59:00Z",
                         "outcomes": [
                             {"name": "New York Mets", "price": -120},
                             {"name": "Cincinnati Reds", "price": 100}]}],
        } for book in books],
    }


class F5ClosePassTests(unittest.TestCase):
    def _run(self, listed, fetch, folder):
        store = Path(folder) / "f5.jsonl"
        with mock.patch.object(dense.odds_provider, "list_events",
                               return_value=listed), \
             mock.patch.object(dense.odds_provider, "fetch_event_odds",
                               side_effect=fetch):
            report = dense._f5_close_pass(None, NOW, store=store)
        return report, store

    def test_only_games_inside_the_close_window_are_fetched(self):
        listed = [_event("near", 10), _event("far", 200),
                  _event("started", -5)]
        fetched = []

        def fetch(event_id, markets, env):
            fetched.append(event_id)
            return _payload(event_id)

        with tempfile.TemporaryDirectory() as folder:
            report, store = self._run(listed, fetch, folder)
        self.assertEqual(fetched, ["near"])
        self.assertEqual(report["events"], 1)
        self.assertEqual(report["rows"], 2)  # two books

    def test_the_pass_is_capped_so_a_big_slate_cannot_multiply_spend(self):
        listed = [_event(f"e{i}", 5 + i) for i in range(10)]

        def fetch(event_id, markets, env):
            return _payload(event_id)

        with tempfile.TemporaryDirectory() as folder:
            report, _ = self._run(listed, fetch, folder)
        self.assertEqual(report["events"], dense.F5_CLOSE_MAX_EVENTS)

    def test_one_event_failing_never_kills_the_pass(self):
        listed = [_event("good", 5), _event("bad", 10)]

        def fetch(event_id, markets, env):
            if event_id == "bad":
                raise dense.odds_provider.OddsProviderError("boom")
            return _payload(event_id)

        with tempfile.TemporaryDirectory() as folder:
            report, store = self._run(listed, fetch, folder)
            rows = [json.loads(l) for l in store.read_text().splitlines()]
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual({r["event_id"] for r in rows}, {"good"})

    def test_rows_carry_the_full_multibook_shape(self):
        listed = [_event("near", 10)]
        with tempfile.TemporaryDirectory() as folder:
            _, store = self._run(listed,
                                 lambda i, markets, env: _payload(i), folder)
            row = json.loads(store.read_text().splitlines()[0])
        for key in ("observed_utc", "event_id", "commence_time", "home_team",
                    "away_team", "market", "book", "book_last_update",
                    "home_price", "away_price"):
            self.assertIn(key, row)
        self.assertEqual(row["market"], dense.F5_CLOSE_MARKET)

    def test_an_unreachable_events_index_is_a_report_not_a_crash(self):
        with mock.patch.object(
                dense.odds_provider, "list_events",
                side_effect=dense.odds_provider.OddsProviderError("down")):
            report = dense._f5_close_pass(None, NOW)
        self.assertEqual(report["events"], 0)
        self.assertEqual(len(report["errors"]), 1)

    def test_no_rows_means_no_file(self):
        with tempfile.TemporaryDirectory() as folder:
            report, store = self._run([], lambda *a, **k: None, folder)
            self.assertFalse(store.exists())
        self.assertEqual(report["rows"], 0)


if __name__ == "__main__":
    unittest.main()
