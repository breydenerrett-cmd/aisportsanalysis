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

    def test_a_killed_pass_does_not_eat_the_next_ones_first_row(self):
        # The F5 store is written by the close pass and nothing else, so a
        # fragment left by a killed run sits at the end of the file until the
        # next close pass -- one night later, one closing line at stake.
        listed = [_event("near", 10)]

        def fetch(event_id, markets, env):
            return _payload(event_id, books=("fanduel",))

        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text('{"event_id":"yesterday","home_pr',
                             encoding="utf-8")
            with mock.patch.object(dense.odds_provider, "list_events",
                                   return_value=listed), \
                 mock.patch.object(dense.odds_provider, "fetch_event_odds",
                                   side_effect=fetch):
                dense._f5_close_pass(None, NOW, store=store)
            lines = store.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["event_id"], "near")


class F5RunSharedStateTests(unittest.TestCase):
    """The pass rides every capture moment, so its budget and its memory are
    the run's, not the moment's."""

    def _run(self, listed, folder, **kwargs):
        store = Path(folder) / "f5.jsonl"
        fetched = []

        def fetch(event_id, markets, env):
            fetched.append(event_id)
            return _payload(event_id, books=("fanduel",))

        with mock.patch.object(dense.odds_provider, "list_events",
                               return_value=listed), \
             mock.patch.object(dense.odds_provider, "fetch_event_odds",
                               side_effect=fetch):
            report = dense._f5_close_pass(None, NOW, store=store, **kwargs)
        return report, fetched, store

    def test_the_lookahead_narrows_the_window_to_the_next_capture(self):
        # Inside the loop a moment is only responsible for games that start
        # before the next capture; the full T-25 reach belongs to the tail.
        listed = [_event("soon", 10), _event("later", 20)]
        with tempfile.TemporaryDirectory() as folder:
            _, fetched, _ = self._run(listed, folder, lookahead_minutes=15)
        self.assertEqual(fetched, ["soon"])

    def test_an_event_already_priced_this_run_is_not_paid_for_twice(self):
        # One credit per event per run is the whole cost argument for hanging
        # this off every capture moment instead of only the last one.
        listed = [_event("near", 10)]
        seen = set()
        with tempfile.TemporaryDirectory() as folder:
            first, fetched, _ = self._run(listed, folder, seen=seen)
            second, again, _ = self._run(listed, folder, seen=seen)
        self.assertEqual(first["events"], 1)
        self.assertEqual(second["events"], 0)
        self.assertEqual(again, [])

    def test_an_event_that_errored_is_not_retried_into_the_budget(self):
        # A market that is not listed errors identically at every moment.
        listed = [_event("bad", 10)]
        seen = set()
        with mock.patch.object(dense.odds_provider, "list_events",
                               return_value=listed), \
             mock.patch.object(
                 dense.odds_provider, "fetch_event_odds",
                 side_effect=dense.odds_provider.OddsProviderError("no market")):
            first = dense._f5_close_pass(None, NOW, seen=seen)
            second = dense._f5_close_pass(None, NOW, seen=seen)
        self.assertEqual(len(first["errors"]), 1)
        self.assertEqual(second["events"], 0)
        self.assertEqual(second["errors"], [])

    def test_an_exhausted_budget_spends_nothing_and_asks_nothing(self):
        listed = [_event("near", 10)]
        with mock.patch.object(dense.odds_provider, "list_events") as index:
            report = dense._f5_close_pass(None, NOW, budget=0)
        self.assertEqual(report, {"events": 0, "rows": 0, "errors": [],
                                  "dropped": []})
        index.assert_not_called()

    def test_the_budget_caps_below_the_standing_maximum(self):
        listed = [_event(f"e{i}", 5 + i) for i in range(10)]
        with tempfile.TemporaryDirectory() as folder:
            report, fetched, _ = self._run(listed, folder, budget=2)
        self.assertEqual(report["events"], 2)
        self.assertEqual(len(fetched), 2)

    def test_the_binding_budget_names_every_game_it_drops(self):
        # DEFECT 2. The cap used to truncate in silence: `seen` and `budget`
        # are per-run and the next run begins after first pitch, so a dropped
        # game is never priced by anything. A permanent loss must be named.
        listed = [_event(f"e{i}", 5 + i) for i in range(5)]
        with tempfile.TemporaryDirectory() as folder:
            report, fetched, _ = self._run(listed, folder, budget=2)
        self.assertEqual(report["events"], 2)
        dropped = report["dropped"]
        self.assertEqual([d["event_id"] for d in dropped],
                         ["e2", "e3", "e4"])
        self.assertTrue(all(d["commence_time"] and d["reason"]
                            for d in dropped))

    def test_a_budget_with_room_drops_nothing(self):
        listed = [_event("only", 10)]
        with tempfile.TemporaryDirectory() as folder:
            report, _, _ = self._run(listed, folder, budget=6)
        self.assertEqual(report["dropped"], [])


class F5MissedReportingTests(unittest.TestCase):
    """The store is the evidence, so the store is what gets checked."""

    def _schedule(self, *minutes):
        return [{"commence_time": (NOW + dt.timedelta(minutes=m))
                 .isoformat().replace("+00:00", "Z")} for m in minutes]

    def test_simultaneous_starts_are_matched_by_identity_not_by_clock(self):
        # DEFECT 1. Four games start at 22:40 on the real 2026-09-01 card.
        # Matching a stored close to a scheduled game on first pitch alone
        # let ONE stored row mark all four covered, so up to three genuinely
        # lost closes reported as zero -- the detector blind to the exact
        # failure it exists to catch.
        start = NOW + dt.timedelta(minutes=10)
        stamp = start.isoformat().replace("+00:00", "Z")
        card = [{"commence_time": stamp, "game_pk": 700 + i,
                 "home_team": home, "away_team": away}
                for i, (home, away) in enumerate(
                    [("New York Mets", "Cincinnati Reds"),
                     ("Chicago Cubs", "Atlanta Braves"),
                     ("Seattle Mariners", "Texas Rangers")])]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text(json.dumps({
                "observed_utc": NOW.isoformat().replace("+00:00", "Z"),
                "commence_time": stamp,
                "home_team": "New York Mets",
                "away_team": "Cincinnati Reds",
            }) + "\n", encoding="utf-8")
            missed = dense._missed_f5_closes(
                card, NOW - dt.timedelta(minutes=45), NOW, store=store)
        self.assertEqual([m["home_team"] for m in missed],
                         ["Chicago Cubs", "Seattle Mariners"])

    def test_identity_matching_survives_the_one_minute_feed_skew(self):
        # The clubs are the key, so the feeds' one-minute disagreement about
        # first pitch cannot turn a stored close into a reported miss.
        start = NOW + dt.timedelta(minutes=10)
        card = [{"commence_time": start.isoformat().replace("+00:00", "Z"),
                 "home_team": "New York Mets", "away_team": "Cincinnati Reds"}]
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text(json.dumps({
                "observed_utc": NOW.isoformat().replace("+00:00", "Z"),
                "commence_time": (start + dt.timedelta(minutes=1))
                .isoformat().replace("+00:00", "Z"),
                "home_team": "new york mets ",
                "away_team": "Cincinnati Reds",
            }) + "\n", encoding="utf-8")
            missed = dense._missed_f5_closes(
                card, NOW - dt.timedelta(minutes=45), NOW, store=store)
        self.assertEqual(missed, [])

    def test_a_store_that_does_not_exist_yet_reports_every_game_missed(self):
        # The state this lane actually spent its first night in.
        with tempfile.TemporaryDirectory() as folder:
            missed = dense._missed_f5_closes(
                self._schedule(10), NOW - dt.timedelta(minutes=45), NOW,
                store=Path(folder) / "absent.jsonl")
        self.assertEqual(len(missed), 1)
        self.assertIn(dense.F5_CLOSE_MARKET, missed[0]["reason"])

    def test_a_one_minute_feed_skew_still_matches_the_stored_close(self):
        # MLB says 22:40, the odds feed says 22:41, every game. Matching on
        # an exact timestamp would report every priced game as missed.
        start = NOW + dt.timedelta(minutes=10)
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text(json.dumps({
                "observed_utc": NOW.isoformat().replace("+00:00", "Z"),
                "commence_time": (start + dt.timedelta(minutes=1))
                .isoformat().replace("+00:00", "Z"),
            }) + "\n", encoding="utf-8")
            missed = dense._missed_f5_closes(
                self._schedule(10), NOW - dt.timedelta(minutes=45), NOW,
                store=store)
        self.assertEqual(missed, [])

    def test_a_stale_close_from_hours_earlier_does_not_count(self):
        # A price taken three hours out is not a close and must not silence
        # the report that says no close exists.
        start = NOW + dt.timedelta(minutes=10)
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text(json.dumps({
                "observed_utc": (start - dt.timedelta(hours=3))
                .isoformat().replace("+00:00", "Z"),
                "commence_time": start.isoformat().replace("+00:00", "Z"),
            }) + "\n", encoding="utf-8")
            missed = dense._missed_f5_closes(
                self._schedule(10), NOW - dt.timedelta(minutes=45), NOW,
                store=store)
        self.assertEqual(len(missed), 1)

    def test_a_fragment_left_by_a_killed_run_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "f5.jsonl"
            store.write_text('{"event_id":"half', encoding="utf-8")
            self.assertEqual(dense._f5_priced(store), [])


if __name__ == "__main__":
    unittest.main()
