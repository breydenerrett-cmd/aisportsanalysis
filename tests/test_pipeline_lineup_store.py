"""Tests for src/pipeline/lineup_store.py.

The properties that matter are the storage properties: an interrupted build
resumes instead of refetching, an off-day is distinguishable from a date never
fetched, and read() hands lineups back keyed the way the detectors ask for them.
The network is faked throughout -- these tests are about the store, not the API.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import lineup_store
from src.providers import mlb


def _lineup(game_pk, *person_ids):
    players = [{"order": i, "person_id": pid, "name": f"Player {pid}",
                "position": "1B"} for i, pid in enumerate(person_ids, 1)]
    return {game_pk: {"game_pk": game_pk, "away": players, "home": []}}


class FakeFetch:
    """Returns canned lineups per date and records which dates were fetched."""

    def __init__(self, by_date):
        self.by_date = by_date
        self.calls = []

    def __call__(self, iso, timeout=20):
        self.calls.append(iso)
        result = self.by_date.get(iso)
        if isinstance(result, Exception):
            raise result
        return result or {}


class TestBuild(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lineups.jsonl"
        self.handedness_calls = []

    def _build(self, dates, fetch, resume=True):
        return lineup_store.build(
            dates, path=self.path, resume=resume, fetch=fetch,
            fetch_handedness=lambda ids, timeout=20:
                self.handedness_calls.append(list(ids)),
            sleep=lambda seconds: None)

    def test_resume_skips_dates_already_stored(self):
        fetch = FakeFetch({"2023-06-01": _lineup(1001, 501),
                           "2023-06-02": _lineup(1002, 502)})
        self._build(["2023-06-01"], fetch)
        report = self._build(["2023-06-01", "2023-06-02"], fetch)
        # The cached date must not hit the network again.
        self.assertEqual(fetch.calls, ["2023-06-01", "2023-06-02"])
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["dates"], 1)

    def test_empty_marker_distinguishes_off_day_from_unfetched(self):
        fetch = FakeFetch({"2023-07-10": {}})  # the All-Star break: no lineups
        self._build(["2023-07-10"], fetch)
        rows = [json.loads(line) for line in
                self.path.read_text().splitlines()]
        self.assertEqual(rows, [{"date": "2023-07-10", "empty": True}])
        # Attempted-and-empty is coverage; a date never passed to build is not.
        self.assertIn("2023-07-10", lineup_store.covered_dates(self.path))
        self.assertNotIn("2023-07-11", lineup_store.covered_dates(self.path))
        # And an off-day is skipped on resume, not refetched forever.
        report = self._build(["2023-07-10"], fetch)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(fetch.calls, ["2023-07-10"])

    def test_failed_date_is_left_absent_so_a_rerun_retries_it(self):
        fetch = FakeFetch({"2023-06-01": mlb.MLBError("boom")})
        report = self._build(["2023-06-01"], fetch)
        self.assertEqual(report["failed"], 1)
        self.assertNotIn("2023-06-01", lineup_store.covered_dates(self.path))

    def test_read_keys_by_game_pk_and_drops_markers(self):
        fetch = FakeFetch({"2023-06-01": _lineup(1001, 501, 502),
                           "2023-06-02": {}})
        self._build(["2023-06-01", "2023-06-02"], fetch)
        store = lineup_store.read(self.path)
        self.assertEqual(set(store), {"1001"})
        self.assertEqual(store["1001"]["date"], "2023-06-01")
        self.assertEqual(
            [slot["person_id"] for slot in store["1001"]["away"]], [501, 502])
        self.assertEqual(store["1001"]["away"][0]["name"], "Player 501")

    def test_read_keys_are_str_to_match_the_results_store(self):
        # history.read_results round-trips game_pk through CSV, so its keys are
        # str. A join between the two stores only works if read() agrees; an
        # int key here makes every cross-store lookup miss silently.
        fetch = FakeFetch({"2023-06-01": _lineup(1001, 501)})
        self._build(["2023-06-01"], fetch)
        store = lineup_store.read(self.path)
        results_style_key = str(1001)  # what a CSV-backed store hands back
        self.assertIn(results_style_key, store)
        self.assertTrue(all(isinstance(k, str) for k in store))

    def test_handedness_cache_extended_once_with_every_person_seen(self):
        fetch = FakeFetch({"2023-06-01": _lineup(1001, 501, 502),
                           "2023-06-02": _lineup(1002, 502, 503)})
        report = self._build(["2023-06-01", "2023-06-02"], fetch)
        self.assertEqual(self.handedness_calls, [[501, 502, 503]])
        self.assertEqual(report["person_ids"], 3)


if __name__ == "__main__":
    unittest.main()
