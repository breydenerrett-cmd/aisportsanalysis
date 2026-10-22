"""The three steps of Send to training over the routes: diagnose, assess, train (api/hounds_interact.py).

The router is faked at the adapter, so the real schema check, cap and cost accounting run and nothing touches a network. Owner
request 2026-10-21: the page shows the work as it happens, so the diagnosis and the AI read are their own read-only calls, and the
training that follows takes the cached read instead of paying for it twice.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

try:
    from fastapi import Response
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover -- Linux CI runs without FastAPI; RouteCase skips every class below
    Response = TestClient = None

from src.hounds import user_store
from src.hounds.interact import coach as coach_mod
from tests._hounds_rites_fixtures import rows_for, write_ledger
from tests.test_hounds_coach import PLAN, FakeAdapter, good_reply, real_router
from tests.test_hounds_rites_api import RouteCase


class Steps(RouteCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = FakeAdapter(good_reply)
        self.shown = coach_mod.Coach(router=real_router(self.tmp.name, self.adapter), context_factory=None)
        patcher = mock.patch.object(coach_mod, "live", lambda: self.shown)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hound_row = self.hound()
        write_ledger(self.ledger, rows_for(self.hound_row["id"], PLAN))

    def diagnose(self, user=None):
        return self.api.training_diagnosis(self.hound_row["id"], Response(), current_user=user or self.owner, _rl=None)

    def assess(self, user=None):
        return self.api.training_assessment(self.hound_row["id"], Response(), current_user=user or self.owner, _rl=None)


class TheReadOnlySteps(Steps):
    def test_diagnose_returns_the_table_and_writes_nothing(self):
        out = self.diagnose()
        self.assertEqual((out["stage"], out["paper_only"], out["diagnosis"]["settled"]), ("diagnose", True, 18))
        self.assertTrue(out["diagnosis"]["rows"] and out["diagnosis"]["ranked"])
        self.assertNotIn("coach", out)
        self.assertEqual(self.adapter.calls, [], "the diagnosis step asks no model")
        self.assertEqual(len(user_store.lineage(self.hound_row["id"])), 1)

    def test_assess_returns_the_ai_read_and_pays_for_it_once(self):
        first = self.assess()
        self.assertEqual((first["coach"]["label"], first["coach"]["resting"]), ("AI read", False))
        self.assertEqual(len(self.adapter.calls), 1)
        self.assess()
        self.assertEqual(len(self.adapter.calls), 1, "a second tap does not buy the same read again")

    def test_the_training_after_them_takes_the_read_and_the_card_cites_it(self):
        self.assess()
        out = self.train(self.hound_row["id"], self.owner)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(out["coach"]["label"], "AI read")
        self.assertTrue(out["coach"]["reasons"] and out["diagnosis"]["checks"] > 10)
        self.assertEqual(out["new"]["version_no"], 2)

    def test_a_stranger_reads_as_not_found_on_both_steps(self):
        for step in (self.diagnose, self.assess):
            exc = self.err(step, self.other)
            self.assertEqual((exc.status_code, self.code(exc)), (404, "not_found"))
        self.assertEqual(self.adapter.calls, [])

    def test_a_house_dog_and_an_open_ticket_are_refused_as_the_training_is(self):
        exc = self.err(self.api.training_diagnosis, "chalk_chihuahua", Response(), current_user=self.owner, _rl=None)
        self.assertEqual((exc.status_code, self.code(exc)), (422, "not_a_member_dog"))
        from tests._hounds_rites_fixtures import NOW, ticket
        write_ledger(self.ledger, ticket(self.hound_row["id"], result=None, start_hours_ago=-3, now=NOW))
        exc = self.err(self.diagnose)
        self.assertEqual((exc.status_code, self.code(exc)), (409, "open_tickets"))
        self.assertEqual(self.adapter.calls, [])

    def test_the_cap_turns_the_assess_step_into_the_rules_engine_read(self):
        capped = coach_mod.Coach(router=real_router(self.tmp.name, self.adapter, cap=0.0000001))
        with mock.patch.object(coach_mod, "live", lambda: capped):
            out = self.assess()
        self.assertEqual((out["coach"]["label"], out["coach"]["resting"]), ("Coach's read (rules engine)", True))
        self.assertEqual(self.adapter.calls, [])
        done = None
        with mock.patch.object(coach_mod, "live", lambda: capped):
            done = self.train(self.hound_row["id"], self.owner)
        self.assertEqual((done["coach"]["label"], done["new"]["version_no"]), ("Coach's read (rules engine)", 2))


class OnTheRealApp(Steps):
    def test_the_routes_are_mounted_need_a_token_and_work_end_to_end(self):
        from api.app import app
        client = TestClient(app)
        base = f"/hounds/{self.hound_row['id']}/train"
        for step in ("/diagnose", "/assess", ""):
            self.assertEqual(client.post(base + step, json={"confirm": True}).status_code, 401, step)
        stranger = {"Authorization": f"Bearer {self.other_token}"}
        self.assertEqual(client.post(base + "/diagnose", headers=stranger).status_code, 404)
        mine = {"Authorization": f"Bearer {self.token}"}
        d = client.post(base + "/diagnose", headers=mine)
        self.assertEqual(d.status_code, 200, d.text)
        self.assertEqual(d.headers["cache-control"], "no-store")
        a = client.post(base + "/assess", headers=mine)
        self.assertEqual(a.status_code, 200, a.text)
        self.assertEqual(a.json()["coach"]["label"], "AI read")
        t = client.post(base, json={"confirm": True}, headers=mine)
        self.assertEqual(t.status_code, 200, t.text)
        self.assertEqual(t.json()["coach"]["label"], "AI read")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_both_read_steps_are_rate_limited_per_user(self):
        # checker 2026-10-21: the limit was wired but never exercised
        from api.app import app
        client = TestClient(app)
        limiter = self.api._training_steps_limiter
        limiter._windows.clear()
        self.addCleanup(limiter._windows.clear)
        mine = {"Authorization": f"Bearer {self.token}"}
        url = f"/hounds/{self.hound_row['id']}/train/diagnose"
        codes = [client.post(url, headers=mine).status_code for _ in range(limiter.limit + 1)]
        self.assertEqual(codes[:limiter.limit], [200] * limiter.limit)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(client.post(url.replace("diagnose", "assess"), headers=mine).status_code, 429)
        self.assertEqual(self.adapter.calls, [], "a refused call asks no model")

    def test_a_training_without_the_confirm_is_still_a_400_and_asks_no_model(self):
        from api.app import app
        client = TestClient(app)
        r = client.post(f"/hounds/{self.hound_row['id']}/train", json={}, headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
