"""The dog-page routes: /d/{id}, /hounds/{id}/rulebook, and the fan-tip box (api/hounds_tips.py,
api/hounds_share.py), through FastAPI's TestClient.

Skipped where FastAPI is not installed (Linux CI has none; src/hounds/fan_tips.py, dials.py and
share_page.py carry the logic and are tested without it in the sibling modules).

ROUTE ORDER is pinned against the real app: the first route that matches /d/<id> must be the share page,
and the first that matches /hounds/tips/export must be the export, not a /hounds/{hound_id} route.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import share_page, stats
from src.hounds.learning import ledger as L

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds_share import router as share_router
    from api.hounds_tips import router as tips_router


APP_SOURCE = (Path(__file__).resolve().parent.parent / "api" / "app.py").read_text(encoding="utf-8")


class MountOrderInTheSource(unittest.TestCase):
    """api/app.py's include order, read as text (this FastAPI keeps an included router as one opaque entry, so
    walking ``app.routes`` finds nothing; tests/test_api_card.py says the same). Runs without FastAPI."""

    def at(self, call):
        self.assertIn(call, APP_SOURCE)
        return APP_SOURCE.index(call)

    def test_the_share_router_is_mounted_early_and_the_tip_router_before_the_race(self):
        health = self.at("app.include_router(health_router)")
        share = self.at("app.include_router(hounds_share_router)")
        create = self.at("app.include_router(hounds_create_router)")
        tips = self.at("app.include_router(hounds_tips_router)")
        learning = self.at("app.include_router(hounds_learning_router)")
        feeds = self.at("app.include_router(feeds_router)")
        race = self.at("app.include_router(hounds_router)")
        web = self.at("app.include_router(web_router)")
        self.assertLess(health, share)
        self.assertLess(share, create)
        self.assertLess(learning, tips)
        self.assertLess(tips, race)
        self.assertLess(feeds, race)
        self.assertLess(share, web)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MountOrderInTheRealApp(unittest.TestCase):
    """The same thing, by asking the real app: the answer must come from the right router."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(Path(cls._tmp.name) / "app.db")})
        cls._env.start()
        from api.app import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls._tmp.cleanup()

    def test_the_share_page_wins_the_slash_d_path(self):
        r = self.client.get("/d/definitely-not-a-dog")
        self.assertIn(r.status_code, (404, 503))                      # the share page's own answers
        self.assertTrue(r.headers["content-type"].startswith("text/html"), r.headers["content-type"])
        self.assertIn("LineHound Kennel", r.text)

    def test_tips_export_is_the_export_and_not_a_hound_called_tips(self):
        r = self.client.get("/hounds/tips/export")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(set(r.json()) >= {"tips", "count", "since"}, True)

    def test_the_tip_routes_answer_before_the_race_router_could(self):
        self.assertEqual(self.client.get("/hounds/steamy_setter/tips").json()["tips"], [])
        self.assertEqual(self.client.get("/hounds/steamy_setter/rulebook").status_code, 200)
        self.assertEqual(self.client.post("/hounds/steamy_setter/tips", json={"values": {"MOVE": 0.9}}).status_code, 400)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TipRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(root / "app.db")})
        env.start()
        self.addCleanup(env.stop)
        scopes = {"house": L.Scope.house(root / "h"), "user": L.Scope.user(root / "u")}
        patch = mock.patch("src.hounds.learning.views.scopes", lambda: scopes)
        patch.start()
        self.addCleanup(patch.stop)
        app = FastAPI()
        app.include_router(tips_router)
        self.client = TestClient(app)

    def post(self, hound="steamy_setter", ip="1.1.1.1", **body):
        return self.client.post(f"/hounds/{hound}/tips", json=body, headers={"Fly-Client-IP": ip})

    def test_send_then_read_back(self):
        r = self.post(values={"MOVE": 0.04}, nickname="Brey 1")
        self.assertEqual(r.status_code, 200, r.text)
        tip = r.json()["tip"]
        self.assertTrue(tip["id"].startswith("tip_"))
        self.assertEqual(r.json()["note"], "Tips are graded like the AI coach's. Only the referee can change a dog.")
        self.assertIs(r.json()["paper_only"], True)
        got = self.client.get("/hounds/steamy_setter/tips").json()
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["tips"][0]["nickname"], "Brey 1")
        self.assertIn("Only the referee can change a dog", got["note"])
        self.assertEqual(self.client.get("/hounds/steamy_setter/tips").headers["cache-control"], "no-store")

    def test_a_bad_tip_is_a_400_that_names_the_field(self):
        r = self.post(values={"MOVE": 0.041})
        self.assertEqual(r.status_code, 400)
        self.assertIn("MOVE", r.json()["detail"]["fields"])
        self.assertEqual(self.post(values={"MOVE": 0.04}, nickname="<b>").status_code, 400)
        self.assertEqual(self.post(hound="coin_flip_collie", values={"X": 1}).status_code, 404)
        self.assertEqual(self.client.get("/hounds/steamy_setter/tips").json()["count"], 0)

    def test_the_fourth_tip_from_one_caller_is_a_429_with_retry_after(self):
        for _ in range(3):
            self.assertEqual(self.post(values={"MOVE": 0.04}).status_code, 200)
        r = self.post(values={"MOVE": 0.04})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["detail"]["error"], "rate_limited")
        self.assertGreater(int(r.headers["retry-after"]), 0)
        self.assertEqual(self.post(values={"MOVE": 0.04}, ip="2.2.2.2").status_code, 200)

    def test_the_export_has_no_address_and_since_filters(self):
        self.post(values={"MOVE": 0.04}, ip="203.0.113.5")
        body = self.client.get("/hounds/tips/export").json()
        self.assertEqual(body["count"], 1)
        row = body["tips"][0]
        self.assertEqual(set(row), {"id", "hound_id", "values", "champion_values", "champion_version", "nickname",
                                    "created_utc"})
        self.assertNotIn("203.0.113.5", self.client.get("/hounds/tips/export").text)
        self.assertEqual(self.client.get("/hounds/tips/export?since=2999-01-01T00:00:00Z").json()["count"], 0)
        self.assertEqual(self.client.get("/hounds/tips/export?since=nonsense").status_code, 400)

    def test_the_rulebook_route_shows_the_dials(self):
        body = self.client.get("/hounds/steamy_setter/rulebook").json()
        self.assertTrue(body["tunable"])
        self.assertEqual(body["dials"][0]["text"], "3 points")
        self.assertIsNone(body["last_changed"])
        none = self.client.get("/hounds/coin_flip_collie/rulebook").json()
        self.assertEqual((none["tunable"], none["dials"]), (False, []))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ShareRoute(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(share_router)
        self.client = TestClient(app)

    def test_a_known_dog_gets_open_graph_tags_and_a_refresh(self):
        info = {"id": "steamy_setter", "name": "Steamy Setter", "tagline": "t", "catchphrase": "Follow the money.",
                "record": {"bets": 10, "wins": 6, "losses": 4, "pushes": 0, "units_average_price": 1.5}}
        with mock.patch.object(share_page, "lookup", lambda hid: (share_page.STATE_OK, info)):
            r = self.client.get("/d/steamy_setter")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertIn('<meta property="og:title" content="Steamy Setter | LineHound Kennel">', r.text)
        self.assertIn("6-4 · +1.50u paper · Follow the money.", r.text)
        self.assertIn("/web/hound.html?id=steamy_setter", r.text)

    def test_an_unknown_dog_is_a_404_page_and_a_cold_kennel_is_a_503(self):
        with mock.patch.object(share_page, "lookup", lambda hid: (share_page.STATE_UNKNOWN, None)):
            r = self.client.get("/d/nobody")
        self.assertEqual(r.status_code, 404)
        self.assertIn("No dog by that name", r.text)
        with mock.patch.object(share_page, "lookup", lambda hid: (share_page.STATE_WARMING, None)):
            r = self.client.get("/d/steamy_setter")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_hostile_ids_are_a_404_and_never_echoed_as_markup(self):
        r = self.client.get("/d/%3Cscript%3Ealert(1)%3C%2Fscript%3E")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("<script", r.text)

    def test_a_real_lookup_through_the_stats_book_when_a_world_exists(self):
        from tests import _hounds_fixtures as F
        from src.hounds.ledgers import Sources
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            with mock.patch.object(Sources, "default", staticmethod(lambda: src)):
                stats.clear_cache()
                stats.get_book(src)
                try:
                    ok = self.client.get("/d/alpha")
                    missing = self.client.get("/d/not-a-dog")
                finally:
                    stats.clear_cache()
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertIn("LineHound Kennel</title>", ok.text)
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
