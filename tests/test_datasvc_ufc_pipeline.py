"""The UFC backfill and update: order, checkpointing, stopping, and status. No network.

The ingestion modules are replaced with fakes so this runs before (and regardless of)
their real implementations; their own tests cover parsing.
"""
import tempfile
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from src.datasvc.http import FetchError, RequestCapReached, SourceBlocked
from src.datasvc.ufc import pipeline
from src.datasvc.ufc.store import UfcStore


class FakeFetcher:
    def __init__(self):
        self.stats = {"requests": 0, "cache_hits": 0}


def bout(bout_id, event_id, a, b, status="final", day="2026-09-26"):
    return {"bout_id": bout_id, "event_id": event_id, "date_utc": f"{day}T21:00Z",
            "fighter_a_id": a, "fighter_b_id": b, "status": status}


class Fakes:
    """Records every call; failure points are set per test."""

    def __init__(self):
        self.calls = []
        self.events = {
            2026: {"e2": [bout("b3", "e2", "f1", "f4")]},
            2025: {"e1": [bout("b1", "e1", "f1", "f2", day="2025-05-01"),
                          bout("b2", "e1", "f3", "f2", day="2025-05-01")]},
        }
        self.stats_error_for = set()
        self.cap_on_event = None
        self.block_on_event = None
        self.upcoming = ([{"event_id": "e9", "date_utc": "2026-10-10T21:00Z"}],
                         [bout("b9", "e9", "f5", "f1", status="scheduled", day="2026-10-10")])

    def namespace(self):
        f = self

        def list_season_events(fetcher, year):
            f.calls.append(("list", year))
            return list(f.events.get(year, {}))

        def crawl_event(fetcher, event_id):
            f.calls.append(("event", event_id))
            if event_id == f.cap_on_event:
                raise RequestCapReached(event_id, None, "cap")
            if event_id == f.block_on_event:
                raise SourceBlocked(event_id, 200, "browser check")
            for year in f.events.values():
                if event_id in year:
                    return {"event_id": event_id, "date_utc": year[event_id][0]["date_utc"]}, year[event_id]
            raise FetchError(event_id, 404, "nope")

        def crawl_season(fetcher, year, since=None, until=None):
            f.calls.append(("season", year, since, until))
            events, bouts = [], []
            for eid, bs in f.events.get(year, {}).items():
                events.append({"event_id": eid, "date_utc": bs[0]["date_utc"]})
                bouts.extend(bs)
            return events, bouts

        def crawl_upcoming(fetcher, today, days=21):
            f.calls.append(("upcoming", today, days))
            return f.upcoming

        def fetch_bout_stats(fetcher, b):
            f.calls.append(("stats", b["bout_id"]))
            if b["bout_id"] in f.stats_error_for:
                raise FetchError(b["bout_id"], 500, "boom")
            return [{"bout_id": b["bout_id"], "fighter_id": b["fighter_a_id"], "date_utc": b["date_utc"]},
                    {"bout_id": b["bout_id"], "fighter_id": b["fighter_b_id"], "date_utc": b["date_utc"]}]

        def fetch_bout_odds(fetcher, b):
            f.calls.append(("odds", b["bout_id"]))
            return [{"bout_id": b["bout_id"], "provider_id": "100", "fetched_utc": "2026-10-03T18:00:00Z"}]

        def fetch_fighters(fetcher, ids):
            f.calls.append(("fighters", tuple(ids)))
            return {"fighters": [{"fighter_id": i, "name": f"Fighter {i}", "fetched_utc": "x"} for i in ids],
                    "not_found": []}

        def fetch_profile(fetcher, fighter):
            f.calls.append(("profile", fighter["fighter_id"]))
            return {"fighter_id": fighter["fighter_id"], "fetched_utc": "x"}

        return types.SimpleNamespace(
            schedule=types.SimpleNamespace(list_season_events=list_season_events, crawl_event=crawl_event,
                                           crawl_season=crawl_season, crawl_upcoming=crawl_upcoming),
            fightstats=types.SimpleNamespace(fetch_bout_stats=fetch_bout_stats),
            odds=types.SimpleNamespace(fetch_bout_odds=fetch_bout_odds),
            fighters=types.SimpleNamespace(fetch_fighters=fetch_fighters),
            ufccom=types.SimpleNamespace(fetch_profile=fetch_profile))


class Backfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))
        self.fakes = Fakes()

    def run_backfill(self, years=(2025, 2026), **kw):
        return pipeline.backfill(years, fetcher=FakeFetcher(), store=self.store,
                                 sources=self.fakes.namespace(), log=lambda *_: None, **kw)

    def test_newest_year_first_then_details_then_fighters_then_profiles(self):
        summary = self.run_backfill()
        kinds = [c[0] for c in self.fakes.calls]
        self.assertEqual(self.fakes.calls[0], ("list", 2026))
        self.assertLess(kinds.index("fighters"), kinds.index("profile"))
        self.assertGreater(kinds.index("fighters"), max(i for i, k in enumerate(kinds) if k == "stats"))
        self.assertEqual((summary["events"], summary["bouts"]), (2, 3))
        self.assertEqual(len(self.store.fight_stats), 6)
        self.assertEqual(len(self.store.odds), 3)
        self.assertEqual(sorted(f["fighter_id"] for f in self.store.fighters), ["f1", "f2", "f3", "f4"])
        self.assertEqual(len(self.store.ufccom_profiles), 4)
        self.assertIsNone(summary["stopped"])
        self.assertTrue((Path(self.tmp.name) / "MANIFEST.json").exists())

    def test_only_missing_fighters_are_requested(self):
        self.store.upsert("fighters", [{"fighter_id": "f1", "name": "Known"}])
        self.run_backfill()
        requested = [c for c in self.fakes.calls if c[0] == "fighters"][0][1]
        self.assertNotIn("f1", requested)

    def test_a_request_cap_stops_cleanly_and_keeps_what_finished(self):
        self.fakes.cap_on_event = "e1"
        summary = self.run_backfill()
        self.assertIn("request cap", summary["stopped"])
        self.assertEqual([e["event_id"] for e in self.store.events], ["e2"])   # 2026 finished first
        self.assertEqual(len(self.store.fight_stats), 2)
        self.assertTrue((Path(self.tmp.name) / "MANIFEST.json").exists())

    def test_a_browser_check_stops_the_whole_run(self):
        self.fakes.block_on_event = "e2"
        summary = self.run_backfill()
        self.assertTrue(summary["stopped"].startswith("source blocked"))
        self.assertNotIn(("list", 2025), self.fakes.calls)
        self.assertEqual(self.store.events, [])

    def test_one_failed_bout_is_recorded_and_the_run_continues(self):
        self.fakes.stats_error_for = {"b1"}
        summary = self.run_backfill()
        self.assertEqual(len(summary["errors"]), 1)
        self.assertIn("b1", summary["errors"][0])
        self.assertEqual(len(self.store.fight_stats), 4)
        self.assertIsNone(summary["stopped"])

    def test_switches_turn_parts_off(self):
        self.run_backfill(stats=False, odds=False, profiles=False)
        kinds = {c[0] for c in self.fakes.calls}
        self.assertFalse(kinds & {"stats", "odds", "profile"})


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))
        self.fakes = Fakes()

    def test_recent_results_and_upcoming_cards(self):
        summary = pipeline.update(date(2026, 10, 3), days_back=10, fetcher=FakeFetcher(), store=self.store,
                                  sources=self.fakes.namespace(), log=lambda *_: None)
        self.assertIn(("season", 2026, date(2026, 9, 23), date(2026, 10, 3)), self.fakes.calls)
        self.assertIn(("upcoming", date(2026, 10, 3), 21), self.fakes.calls)
        # a scheduled bout gets odds, never statistics
        self.assertIn(("odds", "b9"), self.fakes.calls)
        self.assertNotIn(("stats", "b9"), self.fakes.calls)
        self.assertIn("f5", [f["fighter_id"] for f in self.store.fighters])
        self.assertIsNone(summary["stopped"])

    def test_a_window_across_new_year_reads_both_seasons(self):
        pipeline.update(date(2027, 1, 4), days_back=10, fetcher=FakeFetcher(), store=self.store,
                        sources=self.fakes.namespace(), log=lambda *_: None)
        seasons = [c[1] for c in self.fakes.calls if c[0] == "season"]
        self.assertEqual(seasons, [2026, 2027])


class Status(unittest.TestCase):
    def test_counts_newest_and_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcStore(Path(tmp))
            store.upsert("events", [{"event_id": "e1", "date_utc": "2026-10-03T12:00Z"}])
            out = pipeline.status(store, now=datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc))
            self.assertEqual(out["events"], {"records": 1, "newest": "2026-10-03T12:00Z", "age_hours": 6.0})
            self.assertEqual(out["bouts"]["records"], 0)


if __name__ == "__main__":
    unittest.main()
