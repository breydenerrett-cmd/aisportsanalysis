"""POST /hounds/{id}/unleash (api/hounds_interact.py), called directly like the sibling API tests.

A free account keeps one hound and may unleash it (it is the owner's own dog), under the same limits as ever: the dog's
own most-bets-a-day, no live send, no one else's dog. Skipped where FastAPI is not installed.
"""

from __future__ import annotations

import unittest
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import user_engine, user_settle, user_store
from src.hounds.interact import common, drill, fire, manual
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_unleash import NOW, day_rows

if HAS_FASTAPI:
    import tests.test_hounds_interact_api as base
else:  # pragma: no cover
    base = None


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class UnleashRoute(base.ApiCase if HAS_FASTAPI else unittest.TestCase):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(common, "now_utc", lambda: NOW),
                  mock.patch.object(user_engine, "iter_rows", lambda date, sports, **kw: iter(day_rows())),
                  mock.patch.object(user_engine, "_load_game_pk_index", lambda: {}),
                  mock.patch.object(fire, "cached_games", lambda sports, now, rows_for=None: fire.load_games(sports, now, lambda _d, _s: day_rows())),
                  mock.patch.object(user_settle, "settle", lambda **kw: {}),         # grading is not this route's business
                  mock.patch.object(drill, "_local_nfl_results", lambda: (lambda _d: {}))):
            p.start()
            self.addCleanup(p.stop)
        self.free = users_store.create_user("free@example.com", status="active", plan="free", db=self.db)
        self.free_token = users_store.issue_invite_token(self.free.id, db=self.db)
        self.free_dog = user_store.create_hound(
            self.free.id, spec_dict(name="Free Fido", max_bets_per_day=1), free_tier=True,
            now=base.utc("2026-10-20T06:00:00Z"))

    def call(self, hound_id, user):
        return self.api.unleash_today(hound_id, Response(), current_user=user, _rl=None)

    def bets(self, hound_id):
        return [r for r in user_engine.read_ledger(self.ledger)
                if r.get("kind") == user_engine.KIND_BET and r["hound_id"] == hound_id]

    def test_a_free_account_can_unleash_its_own_dog_and_its_daily_limit_still_applies(self):
        out = self.call(self.free_dog["id"], self.free)
        self.assertTrue(out["paper_only"])
        self.assertEqual(out["max_bets_per_day"], 1)
        self.assertEqual(out["placed_now"], 1)                       # two games fit, the dog's own limit is one a day
        self.assertEqual(len(self.bets(self.free_dog["id"])), 1)
        self.assertTrue(out["before"])
        self.assertEqual(out["before_label"], "Before you unleashed. Not on its record.")
        again = self.call(self.free_dog["id"], self.free)
        self.assertTrue(again["already_running"])
        self.assertEqual(len(self.bets(self.free_dog["id"])), 1)

    def test_a_free_account_still_cannot_use_the_paid_live_send_or_unleash_someone_elses_dog(self):
        with self.assertRaises(HTTPException) as ctx:
            self.api.fire_now(self.free_dog["id"], Response(), self.api.FireRequest(event_id="evt-1"),
                              authorization=self.bearer(self.free_token), _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (402, "upgrade_required"))
        with self.assertRaises(HTTPException) as ctx:
            self.call(self.id, self.free)                            # the paid owner's dog
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.bets(self.id), [])

    def test_a_house_dog_and_an_unknown_dog_are_refused(self):
        for hound_id in ("chalk_chihuahua", "no-such-dog"):
            with self.assertRaises(HTTPException) as ctx:
                self.call(hound_id, self.free)
            self.assertEqual(ctx.exception.status_code, 404, hound_id)

    def test_a_signed_out_caller_is_a_401(self):
        from api import auth as auth_mod
        with self.assertRaises(HTTPException) as ctx:
            auth_mod.get_current_user(None, None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_a_buried_dog_is_a_409(self):
        with user_store._connect(self.db) as conn:
            conn.execute("UPDATE hounds SET status = ? WHERE id = ?", (user_store.STATUS_BURIED, self.free_dog["id"]))
        with self.assertRaises(HTTPException) as ctx:
            self.call(self.free_dog["id"], self.free)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (409, "not_running"))

    def test_the_other_picks_can_be_added_as_manual_picks_in_one_request_and_only_once(self):
        out = self.call(self.free_dog["id"], self.free)
        others = [{"event_id": o["event_id"], "market": o["market"]} for o in out["other_picks"] if o["can_record"]]
        self.assertEqual([o["event_id"] for o in others], ["ahead2"])
        body = self.api.ManualBatchRequest(picks=[self.api.ManualRequest(**o) for o in others])
        first = self.api.record_manual_batch(self.free_dog["id"], body, Response(), current_user=self.free, _rl=None)
        self.assertEqual((first["added"], first["skipped"], first["line"]), (1, 0, "Added 1"))
        self.assertTrue(first["paper_only"])
        again = self.api.record_manual_batch(self.free_dog["id"], body, Response(), current_user=self.free, _rl=None)
        self.assertEqual((again["added"], again["skipped"]), (0, 1))
        rows = [r for r in manual.read_all() if r.get("kind") == user_engine.KIND_BET]
        self.assertEqual([r["event_id"] for r in rows], ["ahead2"])
        self.assertEqual(len(self.bets(self.free_dog["id"])), 1)                   # the rule's own record is untouched

    def test_a_batch_on_someone_elses_dog_is_a_404_and_a_started_game_is_skipped(self):
        body = self.api.ManualBatchRequest(picks=[self.api.ManualRequest(event_id="ahead2", market="moneyline")])
        with self.assertRaises(HTTPException) as ctx:
            self.api.record_manual_batch(self.id, body, Response(), current_user=self.free, _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)
        started = self.api.ManualBatchRequest(picks=[self.api.ManualRequest(event_id="play", market="moneyline")])
        out = self.api.record_manual_batch(self.free_dog["id"], started, Response(), current_user=self.free, _rl=None)
        self.assertEqual((out["added"], out["reasons"][0]["reason"]), (0, "game already started"))
        empty = self.api.ManualBatchRequest(picks=[])
        with self.assertRaises(HTTPException) as ctx:
            self.api.record_manual_batch(self.free_dog["id"], empty, Response(), current_user=self.free, _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (422, "no_picks"))

    def test_the_route_is_registered_on_the_router_and_is_a_post(self):
        paths = {(tuple(sorted(r.methods)), r.path) for r in self.api.router.routes if hasattr(r, "methods")}
        self.assertIn((("POST",), "/hounds/{hound_id}/unleash"), paths)
        self.assertIn((("POST",), "/hounds/{hound_id}/manual/batch"), paths)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
