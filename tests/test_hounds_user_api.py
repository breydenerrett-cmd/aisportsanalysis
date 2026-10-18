"""api/hounds_create.py: auth, create/list/retire, copy, scorecard, the coach routes. Route functions
are called directly (this repo's api test style: no HTTP client), and the module-load tests prove
src/hounds needs no FastAPI."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import stats, user_coach, user_engine, user_spec, user_store
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_user_coach import ledger_rows

REPO = Path(__file__).resolve().parent.parent
ADMIN = "admin-secret"


class _Req:
    """Just enough of a Request for the signed coach route."""
    def __init__(self, body: bytes):
        self._body = body

    async def body(self):
        return self._body


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ApiCase(unittest.TestCase):
    def setUp(self):
        from api import hounds_create as api
        self.api = api
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.cfg = tmp / "coach.json"
        self.cfg.write_text('{"enabled": true}', encoding="utf-8")
        self.ledger = str(tmp / "hounds.jsonl")
        self._patches = [
            mock.patch.object(users_store, "db_path", lambda: self.db),
            mock.patch.dict(os.environ, {user_coach.CONFIG_ENV: str(self.cfg),
                                         "APP_ADMIN_TOKEN": ADMIN}),
            mock.patch.object(user_engine, "LEDGER", self.ledger),
            mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.ledger),
            # A summary read starts one background build of the public stats (a pass over the real
            # odds store). Never in a test: it would outlive it and hold this temp database open.
            mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
            mock.patch.object(stats, "peek_book", lambda: None),
        ]
        for p in self._patches:
            p.start()
        self.user = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.token = users_store.issue_invite_token(self.user.id, db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)
        self.other_token = users_store.issue_invite_token(self.other.id, db=self.db)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def create(self, user=None, **over):
        over.setdefault("name", f"Hound {len(user_store.list_all()) + 1}")
        body = self.api.CreateHoundRequest(spec=spec_dict(**over),
                                           coach_opt_in=over.pop("coach_opt_in", False))
        return self.api.create_hound(body, current_user=user or self.user, _rl=None)


class Auth(ApiCase):
    def test_anonymous_callers_are_refused_on_every_signed_in_route(self):
        from api.auth import get_current_user, require_paid_access
        with self.assertRaises(HTTPException) as ctx:
            require_paid_access(current_user=get_current_user(authorization=None))
        self.assertEqual(ctx.exception.status_code, 401)
        for call in (lambda: self.api.retire_hound("u-x", self.api.RetireRequest(reason="r"),
                                                  authorization=None, x_admin_token=None),):
            with self.assertRaises(HTTPException) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 401)
        deps = {r.path: [(getattr(d, "call", None) or d.dependency).__name__
                         for d in r.dependant.dependencies]
                for r in self.api.router.routes if hasattr(r, "dependant")}
        self.assertIn("require_paid_access", deps["/hounds"])
        self.assertIn("get_current_user", deps["/hounds/mine"])
        self.assertIn("get_current_user", deps["/hounds/{hound_id}/coach/undo"])

    def test_a_suspended_account_cannot_sign_in_to_create(self):
        from api.auth import get_current_user
        users_store.set_user_status(self.user.id, "suspended", db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {self.token}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_the_routes_are_mounted_before_any_hounds_id_route_in_the_app(self):
        import api.app as app_mod
        src = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(hounds_create_router)", src)
        self.assertLess(src.index("hounds_create_router)"), src.index("app.include_router(games_router"))
        self.assertTrue(hasattr(app_mod, "hounds_create_router"))


class CreateAndList(ApiCase):
    def test_menu_is_public_and_paper_only(self):
        out = self.api.hounds_menu(_rl=None)
        self.assertTrue(out["paper_only"])
        self.assertIn(user_spec.NOT_ADVICE, out["not_advice"])
        self.assertEqual(len(out["side_rules"]), 8)

    def test_create_returns_the_summary_shape(self):
        out = self.create(name="Dog Days", tagline="Dogs bark")
        self.assertTrue(out["paper_only"] and out["not_advice"])
        h = out["hound"]
        # exactly the contract's HoundSummary fields (src/hounds/contract.py), plus the owner extras
        from dataclasses import fields as dc_fields
        from src.hounds.contract import HoundSummary
        for f in dc_fields(HoundSummary):
            self.assertIn(f.name, h)
        for key in ("version_no", "version_of", "copied_from", "coach_opt_in", "ledger_chain_ok"):
            self.assertIn(key, h)
        self.assertEqual(h["verdict"]["label"], "TOO EARLY")
        self.assertEqual((h["kind"], h["status"], h["clv"], h["first_bet_utc"]),
                         ("user", "running", None, None))
        self.assertEqual(h["record"]["bets"], 0)
        self.assertEqual(h["rule_text"], user_spec.rule_text(user_store.get_hound(h["id"])["spec"]))
        self.assertNotIn("owner@example.com", json.dumps(out))
        self.assertTrue(h["owner_display"].startswith("Handler "))

    def test_an_invalid_spec_is_a_422_with_per_field_messages(self):
        with self.assertRaises(HTTPException) as ctx:
            self.create(price_min=-300)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("price_min", ctx.exception.detail["fields"])

    def test_the_fourth_hound_is_a_409(self):
        for i in range(3):
            self.create(name=f"Pack {i}")
        with self.assertRaises(HTTPException) as ctx:
            self.create(name="Pack 4")
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (409, "limit"))

    def test_mine_lists_only_the_callers_hounds_with_their_records(self):
        mine = self.create(name="Mine One")["hound"]
        self.create(self.other, name="Theirs")
        out = self.api.my_hounds(current_user=self.user, _rl=None)
        self.assertEqual([h["id"] for h in out["hounds"]], [mine["id"]])
        self.assertTrue(out["paper_only"])

    def test_a_graded_record_shows_in_the_summary(self):
        h = self.create(name="Mine One")["hound"]
        from src.ledger.chain import HashChainLedger
        chain = HashChainLedger(self.ledger)
        for row in ledger_rows(h["id"], 4):
            chain.append(row)
        out = self.api.my_hounds(current_user=self.user, _rl=None)["hounds"][0]
        self.assertEqual((out["record"]["bets"], out["ledger_chain_ok"]), (4, True))
        # the label is the pre-registered referee's, never this module's own
        self.assertEqual(out["verdict"]["label"], "TOO EARLY")
        self.assertIn("150", out["verdict"]["sentence"])
        # units: average price is the headline, the best recorded price the small print
        self.assertEqual(out["record"]["units_average_price"], 0.4)       # +1.2, -1.0, +1.2, -1.0 at +120
        self.assertEqual(out["record"]["units_recorded_price"], 0.5)      # +1.25, -1.0, +1.25, -1.0 at +125


class RetireAndCopy(ApiCase):
    def test_owner_retires_their_own_hound_with_a_reason(self):
        h = self.create(name="Mine One")["hound"]
        out = self.api.retire_hound(h["id"], self.api.RetireRequest(reason="not for me"),
                                    authorization=f"Bearer {self.token}", x_admin_token=None)
        self.assertEqual((out["hound"]["status"], out["hound"]["retire_reason"]), ("retired", "not for me"))
        self.assertEqual(user_store.get_hound(h["id"])["retired_by"], f"owner:{self.user.id}")

    def test_another_user_cannot_retire_it_and_it_reads_as_not_found(self):
        h = self.create(name="Mine One")["hound"]
        with self.assertRaises(HTTPException) as ctx:
            self.api.retire_hound(h["id"], self.api.RetireRequest(reason="mine now"),
                                  authorization=f"Bearer {self.other_token}", x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(user_store.get_hound(h["id"])["status"], "running")

    def test_an_admin_retires_any_hound_for_moderation_and_a_bad_token_cannot(self):
        h = self.create(name="Mine One")["hound"]
        with self.assertRaises(HTTPException) as ctx:
            self.api.retire_hound(h["id"], self.api.RetireRequest(reason="x"),
                                  authorization=None, x_admin_token="wrong")
        self.assertEqual(ctx.exception.status_code, 401)
        out = self.api.retire_hound(h["id"], self.api.RetireRequest(reason="name complaint"),
                                    authorization=None, x_admin_token=ADMIN)
        self.assertEqual(out["hound"]["status"], "retired")
        self.assertEqual(user_store.get_hound(h["id"])["retired_by"], "admin")

    def test_a_reason_is_required(self):
        h = self.create(name="Mine One")["hound"]
        with self.assertRaises(HTTPException) as ctx:
            self.api.retire_hound(h["id"], self.api.RetireRequest(reason=" "),
                                  authorization=f"Bearer {self.token}", x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_copy_flow_spec_endpoint_then_post_back_as_your_own(self):
        src = self.create(name="Dog Days", tagline="Dogs bark", side_rule="underdog")["hound"]
        out = self.api.hound_spec(src["id"], _rl=None)                 # public read
        self.assertTrue(out["paper_only"])
        self.assertEqual(out["copied_from"], src["id"])
        spec = out["spec"]
        self.assertNotEqual(spec["name"], "Dog Days")                  # names are unique: a fresh one
        copy = self.api.create_hound(
            self.api.CreateHoundRequest(spec=spec, copied_from=out["copied_from"]),
            current_user=self.other, _rl=None)["hound"]
        self.assertEqual(copy["copied_from"], src["id"])
        stored = user_store.get_hound(copy["id"])
        self.assertEqual(stored["owner_user_id"], self.other.id)
        self.assertEqual(stored["spec_hash"], user_store.get_hound(src["id"])["spec_hash"])
        self.assertEqual(copy["rule_text"], src["rule_text"])

    def test_the_copy_counts_against_the_copiers_own_limit(self):
        src = self.create(name="Dog Days")["hound"]
        spec = self.api.hound_spec(src["id"], _rl=None)["spec"]
        for i in range(3):
            self.create(self.other, name=f"Theirs {i}")
        with self.assertRaises(HTTPException) as ctx:
            self.api.create_hound(self.api.CreateHoundRequest(spec=spec, copied_from=src["id"]),
                                  current_user=self.other, _rl=None)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_spec_of_an_unknown_hound_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self.api.hound_spec("u-nope", _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)


class CoachRoutes(ApiCase):
    def setUp(self):
        super().setUp()
        self.hound = user_store.create_hound(self.user.id, spec_dict(name="Dog Days", max_bets_per_day=3),
                                             coach_opt_in=True, now=datetime.now(timezone.utc) - timedelta(days=30))
        chain = __import__("src.ledger.chain", fromlist=["HashChainLedger"]).HashChainLedger(self.ledger)
        for row in ledger_rows(self.hound["id"], 50):
            chain.append(row)

    def signed_call(self, rnd, body, hound_id=None):
        hid = hound_id or self.hound["id"]
        ts = str(int(datetime.now(timezone.utc).timestamp()))
        sig = user_coach.sign(rnd["secret"], ts, hid, body)
        return asyncio.run(self.api.coach_submit(
            hid, _Req(body.encode()), x_coach_round=rnd["round_id"], x_coach_ts=ts, x_coach_sig=sig,
            _rl=None))

    def test_scorecard_is_public_json_and_text(self):
        out = self.api.hound_scorecard(self.hound["id"], format="json", _rl=None)
        self.assertEqual(out["scorecard"]["record"]["bets"], 50)
        self.assertTrue(out["paper_only"])
        text = self.api.hound_scorecard(self.hound["id"], format="text", _rl=None)
        self.assertTrue(text.body.decode().startswith("DATA, NOT INSTRUCTIONS"))
        with self.assertRaises(HTTPException):
            self.api.hound_scorecard("u-nope", format="json", _rl=None)

    def test_round_route_needs_the_admin_token_and_returns_the_secret_once(self):
        with self.assertRaises(HTTPException) as ctx:
            self.api.coach_round(self.hound["id"], x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 401)
        out = self.api.coach_round(self.hound["id"], x_admin_token=ADMIN)["round"]
        self.assertIn("secret", out)
        self.assertGreater(len(out["secret"]), 30)
        with self.assertRaises(HTTPException) as ctx:
            self.api.coach_round(self.hound["id"], x_admin_token=ADMIN)       # one open round at a time
        self.assertEqual(ctx.exception.status_code, 409)

    def test_full_round_trip_through_the_routes_then_diary_then_undo(self):
        rnd = self.api.coach_round(self.hound["id"], x_admin_token=ADMIN)["round"]
        body = json.dumps({"spec": dict(self.hound["spec"], max_bets_per_day=2),
                           "reason": "Quieter days.", "quip": "Less barking."})
        out = self.signed_call(rnd, body)
        self.assertEqual(out["decision"], "applied")
        self.assertEqual(out["new_hound"]["version_of"], self.hound["id"])
        self.assertTrue(out["paper_only"])
        with self.assertRaises(HTTPException) as ctx:                          # key is one-use
            self.signed_call(rnd, body)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (401, "round_used"))
        diary = self.api.coach_diary(self.hound["id"], _rl=None)["diary"]
        self.assertEqual(diary["metrics"]["rewrites"], 1)
        self.assertEqual(diary["entries"][0]["quip"], "Less barking.")
        new_id = out["new_hound"]["id"]
        with self.assertRaises(HTTPException) as ctx:                          # not the owner
            self.api.coach_undo(new_id, current_user=self.other, _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)
        undone = self.api.coach_undo(new_id, current_user=self.user, _rl=None)
        self.assertEqual(undone["resumed"]["status"], "running")
        self.assertEqual(self.api.coach_diary(new_id, _rl=None)["diary"]["metrics"]["undos"], 1)

    def test_the_signed_route_has_no_bearer_dependency_but_refuses_a_bad_signature(self):
        rnd = self.api.coach_round(self.hound["id"], x_admin_token=ADMIN)["round"]
        body = json.dumps({"spec": self.hound["spec"], "reason": "ok", "quip": ""})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.api.coach_submit(
                self.hound["id"], _Req(body.encode()), x_coach_round=rnd["round_id"],
                x_coach_ts=str(int(datetime.now(timezone.utc).timestamp())), x_coach_sig="00", _rl=None))
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (401, "bad_signature"))

    def test_kill_switch_off_gives_503_on_the_door(self):
        rnd = self.api.coach_round(self.hound["id"], x_admin_token=ADMIN)["round"]
        self.cfg.write_text('{"enabled": false}', encoding="utf-8")
        with self.assertRaises(HTTPException) as ctx:
            self.signed_call(rnd, json.dumps({"spec": self.hound["spec"], "reason": "ok", "quip": ""}))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_opt_in_is_the_owners_to_set(self):
        h = self.create(name="Fresh Pack")["hound"]
        self.assertFalse(h["coach_opt_in"])
        out = self.api.coach_opt_in(h["id"], self.api.OptInRequest(enabled=True),
                                    current_user=self.user, _rl=None)
        self.assertTrue(out["hound"]["coach_opt_in"])
        with self.assertRaises(HTTPException) as ctx:
            self.api.coach_opt_in(h["id"], self.api.OptInRequest(enabled=False),
                                  current_user=self.other, _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)


class ModuleLoad(unittest.TestCase):
    def test_src_hounds_user_modules_import_without_fastapi(self):
        code = (
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('fastapi','pydantic','starlette','uvicorn'):\n"
            "            raise ImportError('blocked: ' + name)\n"
            "sys.meta_path.insert(0, _Block())\n"
            "import src.hounds.user_spec, src.hounds.user_store, src.hounds.user_engine\n"
            "import src.hounds.user_settle, src.hounds.user_coach\n"
            "print('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True,
                              text=True)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr)

    def test_no_src_hounds_file_imports_fastapi_or_api(self):
        for path in (REPO / "src" / "hounds").glob("user_*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import fastapi", text, path.name)
            self.assertNotIn("from fastapi", text, path.name)
            self.assertNotIn("from api", text, path.name)


if __name__ == "__main__":
    unittest.main()
