"""api/hounds_interview.py: the routes, called directly (this repo's api test style), and the seams that need no FastAPI.

Skipped where FastAPI is not installed (Linux CI has none): src/hounds/interview carries all of the logic and is tested
without it in tests/test_hounds_interview.py, and the last class here proves the package imports with FastAPI hidden.
The router is a fake everywhere (`api.hounds_interview.get_router` is replaced), so nothing here touches the network.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import user_store
from tests._hounds_interview_fixtures import Db, FakeRouter, reading, standard_answers

REPO = Path(__file__).resolve().parent.parent
NAME = "Rested Home Dogs"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(Db):
    def setUp(self):
        super().setUp()
        from api import hounds_interview as api
        self.api = api
        self.router = FakeRouter(lambda topic, user: reading())
        self.real_get_router = api.get_router
        patch = mock.patch.object(api, "get_router", lambda: self.router)
        patch.start()
        self.addCleanup(patch.stop)
        keep = mock.patch("api.hounds_interview._send_keep_email", lambda *a, **k: None)
        keep.start()
        self.addCleanup(keep.stop)
        # the hound summary reads the stats book and the ledger; a test must not start its background refresh or read a real ledger
        from src.hounds import stats, user_engine
        self._ledger_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._ledger_dir.cleanup)
        ledger = str(Path(self._ledger_dir.name) / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(user_engine, "ledger_path", lambda path=None: path or ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming"))):
            p.start()
            self.addCleanup(p.stop)
        self.response = Response()

    def refusal(self, fn, *a, **k):
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception

    def start(self, user=None):
        return self.api.start_interview(current_user=user or self.user, _rl=None)

    def answer(self, sid, topic, user=None, **payload):
        body = self.api.AnswerRequest(topic=topic, **payload)
        return self.api.interview_answer(sid, body, self.response, current_user=user or self.user, _rl=None)

    def finish(self, sid, user=None):
        out = None
        for topic, payload in standard_answers():
            out = self.answer(sid, topic, user=user, **payload)
        return out

    def test_the_whole_flow_through_the_routes(self):
        out = self.start()
        sid = out["id"]
        self.assertTrue(out["paper_only"])
        self.assertEqual(out["step"]["topic"], "scope")
        out = self.finish(sid)
        self.assertEqual(out["step"]["kind"], "review")
        shown = self.api.interview_review(sid, self.api.NameRequest(name=NAME), self.response, current_user=self.user, _rl=None)
        self.assertEqual(len(shown["freeze_hash"]), 64)
        self.assertEqual(user_store.list_for_owner(self.user.id, db=self.db), [])
        done = self.api.interview_confirm(sid, self.api.ConfirmRequest(name=NAME, freeze_hash=shown["freeze_hash"]), self.response,
                                          current_user=self.user, _rl=None)
        self.assertEqual(done["record"]["status"], "shadow")
        self.assertEqual(done["hound"]["name"], NAME)
        self.assertEqual(done["hound"]["id"], done["hound_id"])
        self.assertTrue(done["paper_only"])
        rec = self.api.interview_record(done["record_id"], current_user=self.user, _rl=None)
        self.assertEqual(rec["record"]["freeze_hash"], shown["freeze_hash"])

    def test_the_get_returns_the_same_view_and_is_not_cached(self):
        sid = self.start()["id"]
        self.answer(sid, "scope", fields={"sports": ["MLB"], "markets": ["moneyline"], "timing": "pregame"})
        got = self.api.interview_state(sid, self.response, current_user=self.user, _rl=None)
        self.assertEqual(got["step"]["topic"], "side")
        self.assertEqual(self.response.headers["cache-control"], "no-store")
        edit = self.api.interview_state(sid, self.response, edit="scope", current_user=self.user, _rl=None)
        self.assertEqual(edit["step"]["topic"], "scope")
        self.assertEqual(edit["step"]["prefill"]["fields"]["sports"], ["MLB"])

    def test_refusals_carry_stable_codes(self):
        sid = self.start()["id"]
        self.assertEqual(self.refusal(self.api.interview_state, "iv-nope", self.response, current_user=self.user, _rl=None).status_code, 404)
        other = self.refusal(self.api.interview_state, sid, self.response, current_user=self.free, _rl=None)
        self.assertEqual((other.status_code, other.detail["error"]), (404, "not_found"))
        unknown = self.refusal(self.answer, sid, "astrology", fields={})
        self.assertEqual((unknown.status_code, unknown.detail["error"]), (422, "unknown_topic"))
        stuck = self.refusal(self.answer, sid, "scope", skip=True)
        self.assertEqual((stuck.status_code, stuck.detail["error"]), (422, "not_skippable"))
        early = self.refusal(self.api.interview_review, sid, self.api.NameRequest(name=NAME), self.response, current_user=self.user, _rl=None)
        self.assertEqual((early.status_code, early.detail["error"]), (409, "not_ready"))

    def test_a_changed_fingerprint_a_bad_name_and_a_wrong_option(self):
        sid = self.start()["id"]
        self.finish(sid)
        changed = self.refusal(self.api.interview_confirm, sid, self.api.ConfirmRequest(name=NAME, freeze_hash="f" * 64), self.response,
                               current_user=self.user, _rl=None)
        self.assertEqual((changed.status_code, changed.detail["error"]), (409, "changed"))
        rude = self.refusal(self.api.interview_review, sid, self.api.NameRequest(name="Shit Dogs"), self.response, current_user=self.user, _rl=None)
        self.assertEqual((rude.status_code, rude.detail["error"]), (422, "spec_invalid"))
        self.assertIn("name", rude.detail["fields"])
        gone = self.refusal(self.api.interview_resolve, sid, self.api.ResolveRequest(clarification="conflict:side", option="v0"), self.response,
                            current_user=self.user, _rl=None)
        self.assertEqual((gone.status_code, gone.detail["error"]), (409, "not_open"))

    def test_a_free_account_at_its_limit_gets_the_402_the_pages_turn_into_the_upgrade_prompt(self):
        user_store.create_hound(self.free.id, {"version": 1, "name": "First Dog", "tagline": "", "sports": ["MLB"], "markets": ["moneyline"],
                                               "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                                               "max_bets_per_day": 2, "lock_minutes": 120}, free_tier=True, db=self.db)
        with mock.patch("api.auth.is_free_member", lambda user: True):
            denied = self.refusal(self.start, self.free)
        self.assertEqual(denied.status_code, 402)
        self.assertEqual(denied.detail["error"], "upgrade_required")
        self.assertEqual(denied.detail["feature"], "more_dogs")

    def test_a_free_account_that_reaches_the_limit_mid_interview_is_refused_at_confirm(self):
        with mock.patch("api.auth.is_free_member", lambda user: True):
            sid = self.start(self.free)["id"]
            self.finish(sid, self.free)
            user_store.create_hound(self.free.id, {"version": 1, "name": "Other Dog", "tagline": "", "sports": ["MLB"], "markets": ["moneyline"],
                                                   "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                                                   "max_bets_per_day": 2, "lock_minutes": 120}, free_tier=True, db=self.db)
            denied = self.refusal(self.api.interview_confirm, sid, self.api.ConfirmRequest(name=NAME), self.response, current_user=self.free, _rl=None)
        self.assertEqual((denied.status_code, denied.detail["error"], denied.detail["feature"]), (402, "upgrade_required", "more_dogs"))

    def test_the_assistant_is_only_ever_the_injected_router_and_a_broken_one_is_just_the_form(self):
        self.finish(self.start()["id"])
        self.assertTrue(self.router.calls)
        with mock.patch("src.ai.router.default_router", side_effect=RuntimeError("no config")):
            self.assertIsNone(self.real_get_router())
        sentinel = object()
        with mock.patch("src.ai.router.default_router", lambda: sentinel):
            self.assertIs(self.real_get_router(), sentinel)

    def test_the_router_is_mounted_before_the_dog_id_routes(self):
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        interview_at = source.index("app.include_router(hounds_interview_router)")
        self.assertLess(interview_at, source.index("app.include_router(hounds_router)"))
        self.assertLess(source.index("app.include_router(hounds_create_router)"), interview_at)


class TheLogicNeedsNoFastapi(unittest.TestCase):
    def test_the_whole_package_imports_with_fastapi_hidden(self):
        code = ("import sys\n"
                "for n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.hounds.interview as pkg\n"
                "import src.hounds.interview.service, src.hounds.interview.machine, src.hounds.interview.record\n"
                "import src.hounds.interview.extract, src.hounds.interview.derive, src.hounds.interview.store\n"
                "print('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr)

    def test_no_interview_file_imports_fastapi_or_api(self):
        for path in (REPO / "src" / "hounds" / "interview").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("import fastapi", "from fastapi", "from api", "import api"):
                self.assertNotIn(banned, text, path.name)

    def test_nothing_in_the_package_can_place_or_queue_a_bet(self):
        for path in (REPO / "src" / "hounds" / "interview").glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for banned in ("place_bet", "sportsbook_api", "stripe", "betcheck"):
                self.assertNotIn(banned, text, path.name)


if __name__ == "__main__":
    unittest.main()
