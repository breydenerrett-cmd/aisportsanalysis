"""GET /hounds/{id}/report (api/hounds_report.py): who gets the teaser, who gets the full report, and what is cached.

The route is thin wiring over src/hounds/analyze_report.py (tested without FastAPI in test_analyze_report.py); this file proves the
access rules the owner set on 2026-10-29: a FREE TEASER for anyone, the FULL REPORT only for the owner while the owner is paid.
Skipped where FastAPI is not installed (Linux CI has none).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import analyze_report as A, user_store
from tests._hounds_rites_fixtures import NOW, write_ledger
from tests._hounds_user_fixtures import spec_dict
from tests.test_analyze_report import PLAN, rows_of

LOCKED = ["drivers", "keep_it_up", "expand", "coach_read"]


class Fixture:
    """Built once for the whole file: a temp app database and ledger, four kinds of caller (a paid owner, a free owner, another member, a
    visitor) and one 16-7 hound each for the two owners. Account creation hashes tokens, which is what makes a per-test setUp slow."""

    def __init__(self):
        import tempfile
        from pathlib import Path
        from src.hounds import stats, user_engine
        from src.hounds.interact import common
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.db, self.ledger = tmp / "app.db", str(tmp / "hounds_user_v1.jsonl")
        self.patches = [mock.patch.object(users_store, "db_path", lambda: self.db),
                        mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                        mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                        mock.patch.object(stats, "peek_book", lambda: None),
                        mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming")),
                        mock.patch.object(common, "now_utc", lambda: NOW)]
        for p in self.patches:
            p.start()
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)
        self.free = users_store.create_user("free@example.com", status="active", plan="free", db=self.db)
        self.tokens = {u.id: users_store.issue_invite_token(u.id, db=self.db) for u in (self.owner, self.other, self.free)}
        spec = dict(sports=["MLB"], markets=["moneyline"], side_rule="underdog", price_min=-120, price_max=150)
        self.row = user_store.create_hound(self.owner.id, spec_dict(name="Drakeo Pup", **spec))
        self.free_row = user_store.create_hound(self.free.id, spec_dict(name="Free Pup", **spec))
        self.rows = rows_of(PLAN, hid=self.row["id"]) + rows_of(PLAN, hid=self.free_row["id"])
        write_ledger(self.ledger, self.rows)

    def close(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ReportRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()
        cls.addClassCleanup(cls.fx.close)

    def setUp(self):
        from api import auth as auth_mod
        from api import entitlements, hounds_report
        fx = self.fx
        self.api, self.auth, self.entitlements = hounds_report, auth_mod, entitlements
        self.owner, self.other, self.free, self.tokens, self.row, self.free_row = fx.owner, fx.other, fx.free, fx.tokens, fx.row, fx.free_row
        A.clear_caches()
        self.addCleanup(A.clear_caches)
        self.coach_calls = []

        def coach(facts, key, **kw):
            self.coach_calls.append(key)
            return {"text": "Drakeo Pup coach text", "source": "ai", "model": "m", "status": "ok"}
        for p in (mock.patch.object(A, "coach_read", coach),
                  mock.patch.object(A.retune, "live_board_fn", lambda dog, **kw: (lambda spec: None)),
                  mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
                  mock.patch.dict(sys.modules, {"src.hounds.pick_grades": None})):
            p.start()
            self.addCleanup(p.stop)

    def get(self, hound_id=None, user=None, token=None):
        response = Response()
        if user is not None:
            token = self.tokens[user.id]
        out = self.api.hound_report(hound_id or self.row["id"], response, authorization=f"Bearer {token}" if token else None, _rl=None)
        return out, response

    def err(self, **kw):
        with self.assertRaises(HTTPException) as ctx:
            self.get(**kw)
        return ctx.exception

    # ---- who gets what ----

    def test_a_visitor_gets_the_teaser_and_a_public_cache_header(self):
        out, response = self.get()
        self.assertEqual(out["tier"], "teaser")
        self.assertEqual(out["viewer"], {"signed_in": False, "is_owner": False, "full": False})
        self.assertEqual(out["locked"], LOCKED)
        for key in LOCKED:
            self.assertNotIn(key, out)
        self.assertEqual(out["headline"], "Drakeo Pup is 16-7, +48.8% on paper over 23 settled bets.")
        self.assertEqual(len(out["picks"]), 23)
        self.assertEqual(out["hot_hand"]["verdict"], "too_early")
        self.assertIs(out["paper_only"], True)
        self.assertIn("is for the hound's owner", out["upgrade"]["line"])
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=30")
        self.assertEqual(response.headers["Vary"], "Authorization")
        self.assertEqual(self.coach_calls, [])

    def test_a_bad_token_is_just_a_visitor(self):
        out, _ = self.get(token="nonsense")
        self.assertEqual((out["tier"], out["viewer"]["signed_in"]), ("teaser", False))

    def test_another_member_gets_the_teaser_and_is_never_stored(self):
        out, response = self.get(user=self.other)
        self.assertEqual((out["tier"], out["viewer"]), ("teaser", {"signed_in": True, "is_owner": False, "full": False}))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("is for the hound's owner", out["upgrade"]["line"])

    def test_the_paid_owner_gets_the_full_report_never_stored(self):
        out, response = self.get(user=self.owner)
        self.assertEqual((out["tier"], out["viewer"]), ("full", {"signed_in": True, "is_owner": True, "full": True}))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for key in LOCKED:
            self.assertIn(key, out)
        self.assertNotIn("locked", out)
        self.assertNotIn("upgrade", out)
        self.assertEqual(out["coach_read"]["text"], "Drakeo Pup coach text")
        self.assertTrue(out["drivers"]["winning"])
        self.assertEqual(self.coach_calls, [(self.row["id"], 1, 23)])

    def test_a_free_owner_gets_the_teaser_with_the_upgrade_line_not_a_402(self):
        out, response = self.get(self.free_row["id"], user=self.free)
        self.assertEqual((out["tier"], out["viewer"]), ("teaser", {"signed_in": True, "is_owner": True, "full": False}))
        self.assertIn("member plan", out["upgrade"]["line"])
        self.assertEqual(out["upgrade"]["feature"], self.entitlements.FEATURE_ANALYZE)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.coach_calls, [])

    def test_a_lapsed_subscriber_gets_the_teaser(self):
        lapsed = HTTPException(status_code=402, detail={"error": "subscription_expired", "message": "x"})
        with mock.patch.object(self.auth, "require_paid_access", side_effect=lapsed):
            out, _ = self.get(user=self.owner)
        self.assertEqual((out["tier"], out["viewer"]["is_owner"], out["viewer"]["full"]), ("teaser", True, False))

    def test_the_owner_of_someone_elses_hound_is_a_visitor_there(self):
        out, _ = self.get(self.free_row["id"], user=self.owner)
        self.assertEqual((out["tier"], out["viewer"]["is_owner"]), ("teaser", False))

    def test_the_teaser_never_carries_a_hindsight_line(self):
        from src.hounds.interact import common
        key = A.build_report(common.resolve(self.row["id"]), self.fx.rows, now=NOW)["picks"][0]["bet_id"]
        with mock.patch.object(A, "_reviews_for", lambda dog: {key: {"lesson": "A lesson."}}):
            teaser, _ = self.get(user=self.other)
            full, _ = self.get(user=self.owner)
        self.assertTrue(all(p["hindsight"] is None for p in teaser["picks"]))
        self.assertEqual(full["picks"][0]["hindsight"]["label"], "Hindsight review")

    # ---- refusals ----

    def test_a_house_hound_is_a_422_and_an_unknown_one_a_404(self):
        exc = self.err(hound_id="chalk_chihuahua")
        self.assertEqual((exc.status_code, exc.detail["error"]), (422, "not_a_member_dog"))
        exc = self.err(hound_id="no-such-hound")
        self.assertEqual((exc.status_code, exc.detail["error"]), (404, "not_found"))
        exc = self.err(hound_id="../etc")
        self.assertEqual(exc.status_code, 404)

    def test_a_record_still_warming_is_a_503_with_a_retry_after(self):
        from src.hounds.interact import common
        response = Response()
        with mock.patch.object(common, "hound_data", lambda dog: None):
            with self.assertRaises(HTTPException) as ctx:
                self.api.hound_report(self.row["id"], response, authorization=None, _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (503, "warming_up"))
        self.assertEqual(response.headers["Retry-After"], "5")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    # ---- wiring ----

    def test_the_route_is_rate_limited_like_the_other_read_routes(self):
        route = next(r for r in self.api.router.routes if r.path == "/hounds/{hound_id}/report")
        self.assertEqual(route.methods, {"GET"})
        self.assertTrue(any(d.call is self.api._rl_read for d in route.dependant.dependencies))
        self.assertEqual(self.api.READ_PER_MIN, 60)

    def test_it_is_mounted_after_the_hindsight_routes_and_is_not_the_gematria_analysis(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        app_src = (root / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(hounds_report_router)", app_src)
        self.assertLess(app_src.index("app.include_router(hounds_postmortems_router)"), app_src.index("app.include_router(hounds_report_router)"))
        route_src = (root / "api" / "hounds_report.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/hounds/{hound_id}/report")', route_src)
        self.assertNotIn("/analysis", route_src.replace("`/hounds/{id}/analysis` is the Gematria read", ""))

    def test_the_entitlement_helper_agrees_with_the_gate_it_wraps(self):
        ent = self.entitlements
        self.assertFalse(ent.has_paid_dog_tool(self.free))
        self.assertTrue(ent.has_paid_dog_tool(self.owner))
        self.assertEqual(ent.FEATURE_ANALYZE, "analyze")
        self.assertEqual(ent.upgrade_refusal(ent.FEATURE_ANALYZE).detail["error"], "upgrade_required")
        self.assertNotRegex(ent.upgrade_refusal(ent.FEATURE_ANALYZE).detail["message"], r"\bdogs?\b")

    def test_the_mounted_app_serves_the_teaser_and_the_full_report(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:  # pragma: no cover -- no test client in this environment
            self.skipTest("no test client")
        from api.app import app
        client = TestClient(app)
        anon = client.get(f"/hounds/{self.row['id']}/report")
        self.assertEqual((anon.status_code, anon.json()["tier"]), (200, "teaser"))
        with mock.patch.object(self.auth, "optional_user_id", lambda authorization: self.owner.id if authorization else None):
            full = client.get(f"/hounds/{self.row['id']}/report", headers={"Authorization": "Bearer x"})
        self.assertEqual((full.status_code, full.json()["tier"], full.headers["cache-control"]), (200, "full", "no-store"))
        self.assertEqual(client.get("/hounds/chalk_chihuahua/report").status_code, 422)


if __name__ == "__main__":
    unittest.main()
