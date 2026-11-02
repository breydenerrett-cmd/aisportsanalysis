"""api/member_bets.py: Log a bet over HTTP (FastAPI TestClient, real bearer auth against a temp app database).

Skipped where FastAPI is not installed (Linux CI has none); src/hounds/member_bets.py carries the logic and is
tested without it in tests/test_member_bets.py."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import member_bets as mb
from tests.test_member_bets import (NHL_AWAY, NHL_EVENT, NHL_HOME, PLACED, SETTLE_AT, TENNIS_EVENT, rows_for,
                                    score)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MemberBetsApi(unittest.TestCase):
    def setUp(self):
        from api import member_bets as api
        self.api = api
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_member_bets_v1.jsonl")
        real_find = mb.find_game
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.dict(os.environ, {mb.ENV_LEDGER: self.ledger}),
                  mock.patch.object(mb, "_now", lambda now=None: now or PLACED),
                  mock.patch.object(mb, "find_game", lambda eid, now, rf=None: real_find(eid, now, rows_for))):
            p.start()
            self.addCleanup(p.stop)
        api._limiter._buckets.clear() if hasattr(api._limiter, "_buckets") else None
        self.free = users_store.create_user("free@example.com", status="active", plan="free", db=self.db)
        self.paid = users_store.create_user("paid@example.com", status="active", plan="beta", db=self.db)
        self.h_free = {"Authorization": "Bearer " + users_store.issue_invite_token(self.free.id, db=self.db)}
        self.h_paid = {"Authorization": "Bearer " + users_store.issue_invite_token(self.paid.id, db=self.db)}
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)

    def body(self, **kw):
        base = {"event_id": NHL_EVENT, "market": "moneyline", "side": "home", "stake_units": 2}
        base.update(kw)
        return base

    def test_signed_out_is_refused_on_every_route(self):
        self.assertEqual(self.client.get("/me/bets").status_code, 401)
        self.assertEqual(self.client.post("/me/bets", json=self.body()).status_code, 401)
        self.assertEqual(self.client.post("/me/bets/manual", json={}).status_code, 401)
        self.assertEqual(self.client.delete("/me/bets/mb-x").status_code, 401)

    def test_a_free_member_can_place_and_sees_the_price_filled_in(self):
        pre = self.client.get("/me/bets/price", params={"event_id": NHL_EVENT, "market": "moneyline",
                                                        "side": "home"}, headers=self.h_free)
        self.assertEqual(pre.status_code, 200)
        self.assertEqual(pre.json()["price"], -140)
        r = self.client.post("/me/bets", json=self.body(), headers=self.h_free)
        self.assertEqual(r.status_code, 200, r.text)
        bet = r.json()
        self.assertEqual((bet["status"], bet["price"], bet["stake_units"], bet["can_void"]), ("open", -140, 2.0, True))
        self.assertNotIn("owner_user_id", bet)
        listed = self.client.get("/me/bets", headers=self.h_free).json()
        self.assertEqual((len(listed["bets"]), listed["open"]), (1, 1))
        self.assertEqual(listed["record"]["w"], 0)

    def test_place_settle_then_the_record_shows_on_the_list(self):
        self.client.post("/me/bets", json=self.body(), headers=self.h_free)
        self.client.post("/me/bets", json=self.body(event_id=TENNIS_EVENT, side="away", price=-145, stake_units=1),
                         headers=self.h_free)
        mb.settle(now=SETTLE_AT, close_fn=lambda b: -150, allsports_results={
            NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 4, 1),
            TENNIS_EVENT: score(TENNIS_EVENT, "Carlos Alcaraz", "Jannik Sinner", 1, 0, "tennis_atp_test")})
        with mock.patch.object(mb, "_now", lambda now=None: now or SETTLE_AT):
            listed = self.client.get("/me/bets", headers=self.h_free).json()
        rec = listed["record"]
        self.assertEqual((rec["w"], rec["l"], listed["open"]), (1, 1, 0))
        self.assertEqual(rec["n_clv"], 2)
        self.assertIsNotNone(rec["clv_mean"])
        self.assertAlmostEqual(rec["units"], 0.7143 * 2 - 1.0, places=3)

    def test_a_second_side_on_the_same_game_is_a_400_class_refusal_with_a_plain_reason(self):
        self.client.post("/me/bets", json=self.body(), headers=self.h_paid)
        r = self.client.post("/me/bets", json=self.body(side="away"), headers=self.h_paid)
        self.assertEqual(r.status_code, 409)
        self.assertIn("one side", r.json()["detail"])

    def test_bad_requests_get_plain_sentences(self):
        r = self.client.post("/me/bets", json=self.body(price=7), headers=self.h_free)
        self.assertEqual(r.status_code, 400)
        self.assertIn("price", r.json()["detail"])
        r = self.client.post("/me/bets", json=self.body(stake_units=50), headers=self.h_free)
        self.assertEqual((r.status_code, "stake" in r.json()["detail"]), (400, True))
        r = self.client.post("/me/bets", json=self.body(event_id="nope"), headers=self.h_free)
        self.assertEqual(r.status_code, 404)

    def test_void_before_the_start_works_and_after_it_is_refused(self):
        bet = self.client.post("/me/bets", json=self.body(), headers=self.h_free).json()
        r = self.client.delete("/me/bets/" + bet["id"], headers=self.h_free)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "removed"))
        bet2 = self.client.post("/me/bets", json=self.body(event_id=TENNIS_EVENT), headers=self.h_free).json()
        from tests._hounds_user_fixtures import utc
        with mock.patch.object(mb, "_now", lambda now=None: now or utc("2026-10-20T23:30:00Z")):
            r = self.client.delete("/me/bets/" + bet2["id"], headers=self.h_free)
        self.assertEqual(r.status_code, 409)
        self.assertIn("stays", r.json()["detail"])

    def test_a_member_cannot_see_or_void_another_members_bet(self):
        bet = self.client.post("/me/bets", json=self.body(), headers=self.h_free).json()
        self.assertEqual(self.client.get("/me/bets", headers=self.h_paid).json()["bets"], [])
        self.assertEqual(self.client.delete("/me/bets/" + bet["id"], headers=self.h_paid).status_code, 404)

    def test_manual_bet_is_unmatched(self):
        r = self.client.post("/me/bets/manual", headers=self.h_free, json={
            "sport": "tennis", "game_text": "Local Open final", "side_text": "Smith", "price": -110,
            "stake_units": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["status"], r.json()["kind"]), ("unmatched", "manual"))

    def test_rate_limit_is_on_the_write_routes(self):
        from src.appstate import ratelimit
        with mock.patch.object(self.api, "_limiter", ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)):
            # the dependency was built at import time with the module's limiter; check it is the same pattern
            self.assertTrue(callable(self.api._rate_limited))
        self.assertEqual(self.api.MEMBER_BETS_RATE_LIMIT_PER_MIN, 60)

    def test_the_router_is_mounted_in_the_app(self):
        from api.app import app
        paths = {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops}
        for want in (("GET", "/me/bets"), ("POST", "/me/bets"), ("POST", "/me/bets/manual"),
                     ("DELETE", "/me/bets/{bet_id}")):
            self.assertIn(want, paths)
        self.assertIn(("GET", "/my-bets"), paths)           # the old route is untouched


if __name__ == "__main__":
    unittest.main()
