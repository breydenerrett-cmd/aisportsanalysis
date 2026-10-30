"""The fine-tune / full-rebuild routes (api/hounds_interact.py): options, fine-tune, rebuild, job, plan/apply.

Thin wiring over src/hounds/interact/training_plans.py (tested without FastAPI in test_training_plans.py). This file proves the wiring:
only the owner may start a job, read it or apply its plan; a missing key is a 503 "unavailable right now" answered at once, with no
job and no spend; Apply needs the confirm and only a plan id (the page never sends a rule set). Skipped where FastAPI is not installed.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest import mock

try:
    from fastapi import Response
except ImportError:  # pragma: no cover
    Response = None

from src.hounds import user_store
from src.hounds.interact import rebuild_ai, rebuild_budget as budget, training_plans as plans
from tests._hounds_rites_fixtures import write_ledger
from tests.test_hounds_rites_api import RouteCase
from tests.test_training_plans import ENV, MIXED, FakeClient, fake_replay, standard_responder
from tests._hounds_rites_fixtures import rows_for


@unittest.skipIf(Response is None, "FastAPI is not installed")
class Routes(RouteCase):
    def setUp(self):
        super().setUp()
        import tempfile
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        env = {budget.LEDGER_ENV: os.path.join(self._d.name, "rebuild_usage.jsonl"), "ANTHROPIC_API_KEY": ENV["ANTHROPIC_API_KEY"]}
        # production rehearses a rebuild's candidates in one batch (``default_replay_many``) beside the single drill (``default_replay``): both are faked
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(plans, "default_replay", fake_replay),
                  mock.patch.object(plans, "default_replay_many", lambda specs, days, now: [fake_replay(sp, days, now) for sp in specs]),
                  mock.patch.object(rebuild_ai, "_default_client", lambda key: FakeClient(standard_responder())),
                  mock.patch.object(budget, "router_headroom", lambda *a, **k: None),
                  mock.patch.object(budget, "log_usage_to_router", lambda *a, **k: None),
                  mock.patch.object(plans, "_plans", plans.PlanStore(os.path.join(self._d.name, "plans"))),
                  mock.patch.object(plans, "_jobs", plans.JobBoard())):
            p.start()
            self.addCleanup(p.stop)
        patch = mock.patch.object(self.api, "_is_paid", lambda user: False)          # a free member: one rebuild a day
        patch.start()
        self.addCleanup(patch.stop)
        self.hound_row = self.dog("Rusty Pup", sports=["MLB", "NFL"], markets=["moneyline", "spread"], side_rule="underdog")
        write_ledger(self.ledger, rows_for(self.hound_row["id"], MIXED))

    def wait(self, job_id, user=None):
        for _ in range(200):
            view = self.api.training_job(self.hound_row["id"], job_id, Response(), current_user=user or self.owner, _rl=None)
            if view["state"] != "running":
                return view
            time.sleep(0.05)
        self.fail("the job never finished")

    def start(self, which, user=None):
        fn = {"fine": self.api.training_fine_tune, "rebuild": self.api.training_rebuild}[which]
        return fn(self.hound_row["id"], Response(), current_user=user or self.owner, _rl=None)

    def test_options_say_what_is_available(self):
        out = self.api.training_options(self.hound_row["id"], Response(), current_user=self.owner, _rl=None)
        self.assertTrue(out["fine_tune"]["available"])
        self.assertEqual((out["rebuild"]["available"], out["rebuild"]["left_today"], out["rebuild"]["used_today"]), (True, 1, 0))

    def test_options_without_a_key_say_unavailable_right_now_and_do_not_error(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            out = self.api.training_options(self.hound_row["id"], Response(), current_user=self.owner, _rl=None)
        self.assertFalse(out["rebuild"]["available"])
        self.assertIn("unavailable right now", out["rebuild"]["reason"])
        self.assertTrue(out["fine_tune"]["available"])

    def test_a_rebuild_without_a_key_is_a_503_at_once_and_starts_no_job(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            exc = self.err(self.start, "rebuild")
        self.assertEqual((exc.status_code, self.code(exc)), (503, "unavailable"))
        self.assertEqual(plans.jobs()._jobs, {})

    def test_a_fine_tune_job_runs_and_its_plan_applies_by_id(self):
        started = self.start("fine")
        self.assertEqual(started["kind"], "minor")
        done = self.wait(started["job_id"])
        self.assertEqual(done["state"], "done")
        card = done["result"]
        self.assertTrue(card["found"])
        exc = self.err(self.api.training_plan_apply, self.hound_row["id"], self.api.PlanApplyRequest(plan_id=card["plan_id"], confirm=False),
                       Response(), current_user=self.owner, _rl=None)
        self.assertEqual(self.code(exc), "confirm_required")
        out = self.api.training_plan_apply(self.hound_row["id"], self.api.PlanApplyRequest(plan_id=card["plan_id"], basis=card["basis"], confirm=True),
                                           Response(), current_user=self.owner, _rl=None)
        self.assertEqual(out["origin"], user_store.ORIGIN_FINE_TUNE)
        self.assertEqual(user_store.get_hound(out["new"]["id"], db=self.db)["version_no"], 2)

    def test_a_rebuild_job_runs_through_the_route_and_counts_the_day(self):
        done = self.wait(self.start("rebuild")["job_id"])
        self.assertEqual(done["state"], "done", done)
        self.assertTrue(done["result"]["found"])
        exc = self.err(self.start, "rebuild")
        self.assertEqual((exc.status_code, self.code(exc)), (429, "daily_limit"))

    def test_nobody_else_can_start_read_or_apply(self):
        exc = self.err(self.start, "fine", self.other)
        self.assertEqual(exc.status_code, 404)
        job = self.start("fine")
        self.wait(job["job_id"])
        exc = self.err(self.api.training_job, self.hound_row["id"], job["job_id"], Response(), current_user=self.other, _rl=None)
        self.assertEqual(exc.status_code, 404)
        card = plans.jobs().get(job["job_id"], self.owner.id)["result"]
        exc = self.err(self.api.training_plan_apply, self.hound_row["id"], self.api.PlanApplyRequest(plan_id=card["plan_id"], confirm=True),
                       Response(), current_user=self.other, _rl=None)
        self.assertEqual(exc.status_code, 404)

    def test_the_routes_are_registered(self):
        paths = {(r.path, tuple(sorted(r.methods))) for r in self.api.router.routes}
        for path, method in (("/hounds/{hound_id}/train/options", "GET"), ("/hounds/{hound_id}/train/fine-tune", "POST"),
                             ("/hounds/{hound_id}/train/rebuild", "POST"), ("/hounds/{hound_id}/train/job/{job_id}", "GET"),
                             ("/hounds/{hound_id}/train/plan/apply", "POST")):
            self.assertIn((path, (method,)), paths)


if __name__ == "__main__":
    unittest.main()
