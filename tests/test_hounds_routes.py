"""GET /hounds routes against the synthetic world.

Skipped where FastAPI is not installed (Linux CI has none; the core is tested
without it in tests/test_hounds_core.py).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import NOT_ADVICE, stats
from src.hounds.ledgers import Sources
from tests import _hounds_fixtures as F

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        src = F.make_world(Path(cls._tmp.name))
        cls._patch = mock.patch.object(Sources, "default", staticmethod(lambda: src))
        cls._patch.start()
        stats.clear_cache()
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        stats.clear_cache()
        cls._tmp.cleanup()

    def get(self, url, status=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def assertStamped(self, body):
        self.assertIs(body["paper_only"], True)
        self.assertEqual(body["not_advice"], NOT_ADVICE)

    def test_leaderboard(self):
        body = self.get("/hounds")
        self.assertStamped(body)
        self.assertEqual(body["as_of"], "2026-10-02")
        self.assertIn("Paper only", body["basis"])
        ids = [h["id"] for h in body["hounds"]]
        self.assertEqual(set(ids), {"alpha", "bravo", "charlie", "delta", "u-1"})
        self.assertEqual(ids[-1], "bravo")                  # baseline does not lead
        alpha = next(h for h in body["hounds"] if h["id"] == "alpha")
        self.assertEqual(alpha["record"]["bets"], 3)
        self.assertEqual(alpha["spark"], [0.0, -0.187])
        self.assertIn(alpha["verdict"]["label"], ("TOO EARLY",))
        self.assertIn("say nothing", alpha["verdict"]["units_note"])

    def test_detail_has_series_and_first_page_of_bets_newest_first(self):
        body = self.get("/hounds/alpha")
        self.assertStamped(body)
        self.assertEqual(body["id"], "alpha")
        self.assertEqual([p["date"] for p in body["series"]], ["2026-09-30", "2026-10-01"])
        self.assertEqual(body["bets"]["total"], 5)          # 4 forward + 1 replay
        dates = [b["date"] for b in body["bets"]["items"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(body["bets"]["items"][0]["segment"], "replay")

    def test_bets_paging_and_segment_filter(self):
        p1 = self.get("/hounds/alpha/bets?page=1&page_size=2")
        p3 = self.get("/hounds/alpha/bets?page=3&page_size=2")
        self.assertEqual((len(p1["items"]), p1["pages"], len(p3["items"])), (2, 3, 1))
        fwd = self.get("/hounds/alpha/bets?segment=forward")
        self.assertEqual(fwd["total"], 4)
        self.assertTrue(all(b["segment"] == "forward" for b in fwd["items"]))
        self.get("/hounds/alpha/bets?segment=bogus", status=422)
        self.get("/hounds/alpha/bets?page=0", status=422)

    def test_stream_pages_and_marks_refusals(self):
        body = self.get("/hounds/stream?page=1&page_size=3")
        self.assertStamped(body)
        self.assertEqual(len(body["items"]), 3)
        allrows = []
        for page in (1, 2, 3, 4):
            allrows += self.get(f"/hounds/stream?page={page}&page_size=3")["items"]
        self.assertEqual(sum(1 for i in allrows if i["refused"]), 1)
        self.assertEqual(len(allrows), body["total"])

    def test_graveyard_is_empty_here_and_stamped(self):
        body = self.get("/hounds/graveyard")
        self.assertStamped(body)
        self.assertEqual(body["hounds"], [])

    def test_series_route(self):
        body = self.get("/hounds/series?ids=alpha,charlie,nope")
        self.assertStamped(body)
        self.assertEqual(set(body["series"]), {"alpha", "charlie"})
        self.assertEqual(set(body["series"]["alpha"][0]), {
            "date", "cum_units_average_price", "cum_units_recorded_price",
            "bets_settled", "cum_clv_mean_pts"})
        self.assertEqual(self.get("/hounds/series")["series"], {})

    def test_static_paths_are_not_read_as_hound_ids(self):
        self.assertIn("items", self.get("/hounds/stream"))
        self.assertIn("series", self.get("/hounds/series?ids=alpha"))
        self.assertIn("hounds", self.get("/hounds/graveyard"))

    def test_unknown_hound_is_404(self):
        self.get("/hounds/nope", status=404)
        self.get("/hounds/nope/bets", status=404)

    def test_only_get_routes_exist(self):
        r = self.client.post("/hounds", json={})
        self.assertEqual(r.status_code, 405)
        self.assertEqual(self.client.delete("/hounds/alpha").status_code, 405)

    def test_public_cache_header(self):
        r = self.client.get("/hounds")
        self.assertIn("max-age", r.headers["cache-control"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MountedInTheRealApp(unittest.TestCase):
    def test_app_mounts_hounds_without_auth(self):
        from api.app import app
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            with mock.patch.object(Sources, "default", staticmethod(lambda: src)):
                stats.clear_cache()
                client = TestClient(app)
                r = client.get("/hounds")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertIs(r.json()["paper_only"], True)
                stats.clear_cache()


if __name__ == "__main__":
    unittest.main()
