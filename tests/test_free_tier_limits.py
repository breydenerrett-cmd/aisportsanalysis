"""The free tier (owner decision 2026-10-20): one active dog, and no Live send, Backtest or Ask on a member dog.

Paid (a subscriber, a COMP, a tester window, an invited beta user) runs up to five dogs and every tool.
Existing free accounts that already hold more than one dog are GRANDFATHERED: they keep every dog, they just
cannot add another (docs/support/FREE_MEMBERS.md, "Free vs member").

The store tests need no FastAPI (Linux CI has none); the route tests skip without it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import users as users_store
from src.hounds import user_spec, user_store
from tests._hounds_user_fixtures import spec_dict

WORDS = ("Alpha", "Bravo", "Cedar", "Delta", "Ember", "Fargo")


class StoreLimits(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        self.free = users_store.create_user("free@example.com", status="active", plan="free", db=self.db)

    def make(self, i, **kw):
        return user_store.create_hound(self.free.id, spec_dict(name=f"{WORDS[i]} Dog"), **kw)

    def test_the_numbers_are_the_owners(self):
        self.assertEqual((user_spec.FREE_MAX_ACTIVE_PER_ACCOUNT, user_spec.MAX_RUNNING_PER_ACCOUNT), (1, 5))

    def test_a_free_account_gets_one_dog_and_a_second_is_upgrade_required(self):
        self.make(0, free_tier=True)
        with self.assertRaises(user_store.StoreError) as ctx:
            self.make(1, free_tier=True)
        self.assertEqual(ctx.exception.code, "upgrade_required")

    def test_a_benched_dog_still_holds_the_free_slot(self):
        first = self.make(0, free_tier=True)
        user_store.set_status(first["id"], user_store.STATUS_BENCHED) if hasattr(user_store, "set_status") \
            else self._bench(first["id"])
        with self.assertRaises(user_store.StoreError) as ctx:
            self.make(1, free_tier=True)
        self.assertEqual(ctx.exception.code, "upgrade_required")

    def _bench(self, hound_id):
        with user_store._connect(self.db) as conn:
            conn.execute("UPDATE hounds SET status = ? WHERE id = ?", (user_store.STATUS_BENCHED, hound_id))

    def test_removing_the_dog_frees_the_slot(self):
        first = self.make(0, free_tier=True)
        user_store.retire_hound(first["id"], by="owner", reason="done")
        self.assertEqual(self.make(1, free_tier=True)["spec"]["name"], "Bravo Dog")

    def test_paid_accounts_run_five_and_the_sixth_is_the_ordinary_limit(self):
        for i in range(5):
            self.make(i)
        with self.assertRaises(user_store.StoreError) as ctx:
            self.make(5)
        self.assertEqual(ctx.exception.code, "limit")

    def test_grandfathered_free_accounts_keep_every_dog_but_cannot_add_one(self):
        for i in range(3):                       # the three the old limit allowed, made before the rule
            self.make(i)
        with self.assertRaises(user_store.StoreError) as ctx:
            self.make(3, free_tier=True)
        self.assertEqual(ctx.exception.code, "upgrade_required")
        mine = user_store.list_for_owner(self.free.id)
        self.assertEqual([h["status"] for h in mine], ["running"] * 3)       # nothing retired, nothing benched

    def test_a_grandfathered_account_can_add_again_only_after_dropping_below_one(self):
        dogs = [self.make(i) for i in range(2)]
        user_store.retire_hound(dogs[0]["id"], by="owner", reason="done")
        with self.assertRaises(user_store.StoreError):
            self.make(2, free_tier=True)         # one left: at the free limit
        user_store.retire_hound(dogs[1]["id"], by="owner", reason="done")
        self.assertEqual(self.make(2, free_tier=True)["status"], "running")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteRefusals(unittest.TestCase):
    def setUp(self):
        import tests.test_hounds_interact_api as base

        class Case(base.ApiCase):
            def runTest(self):  # pragma: no cover - never run, only set up
                pass

        self.case = Case()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        c = self.case
        self.c = c
        c.free = users_store.create_user("free@example.com", status="active", plan="free", db=c.db)
        c.free_token = users_store.issue_invite_token(c.free.id, db=c.db)
        from api import hounds_create as create_api
        self.create_api = create_api

    def refusal(self, fn, *a, **k):
        with self.assertRaises(HTTPException) as ctx:
            fn(*a, **k)
        return ctx.exception

    def assert_upgrade(self, exc, feature):
        self.assertEqual(exc.status_code, 402)
        self.assertEqual(exc.detail["error"], "upgrade_required")
        self.assertEqual(exc.detail["feature"], feature)
        self.assertTrue(exc.detail["message"])

    # ---- Ask, Live send, Backtest on a member dog -----------------------------------------------

    def ask(self, token):
        return self.c.api.ask_dog(self.c.id, self.c.api.AskRequest(question="what did you bet today"), Response(),
                                  authorization=self.c.bearer(token) if token else None, _rl=None)

    def live(self, token):
        return self.c.api.fire_now(self.c.id, Response(), self.c.api.FireRequest(event_id="evt-1"),
                                   authorization=self.c.bearer(token) if token else None, _rl=None)

    def drill(self, token_user, dog_id=None):
        return self.c.api.run_drill(self.c.api.DrillRequest(dog_id=dog_id or self.c.id, days=7), Response(),
                                    current_user=token_user, _rl=None)

    def test_a_free_account_is_refused_ask_live_send_and_backtest_on_a_member_dog(self):
        self.assert_upgrade(self.refusal(self.ask, self.c.free_token), "ask")
        self.assert_upgrade(self.refusal(self.live, self.c.free_token), "live_send")
        self.assert_upgrade(self.refusal(self.drill, self.c.free), "backtest")

    def test_a_signed_out_caller_is_a_401_not_a_402(self):
        self.assertEqual(self.refusal(self.ask, None).status_code, 401)
        self.assertEqual(self.refusal(self.live, None).status_code, 401)

    def test_a_paid_account_is_not_refused(self):
        out = self.ask(self.c.owner_token)
        self.assertIn("answer", out)
        try:
            self.live(self.c.owner_token)
        except HTTPException as exc:                          # an unknown game is fine; a payment wall is not
            self.assertNotEqual(exc.detail.get("error"), "upgrade_required")

    def test_a_comped_account_counts_as_paid(self):
        from src.appstate import comps
        comps.grant_comp(user_id=self.c.free.id, reason="owner comp", db=self.c.db)
        token = users_store.issue_invite_token(self.c.free.id, db=self.c.db)
        self.assertIn("answer", self.ask(token))
        try:
            self.live(token)
        except HTTPException as exc:
            self.assertNotEqual(exc.detail.get("error"), "upgrade_required")

    def test_the_plain_preview_and_house_dogs_stay_open_to_a_free_account(self):
        out = self.c.api.fire_now(self.c.id, Response(), None, authorization=self.c.bearer(self.c.free_token), _rl=None)
        self.assertIn("picks", out)
        house = self.c.api.ask_dog("chalk_chihuahua", self.c.api.AskRequest(question="what are your rules"),
                                   Response(), authorization=None, _rl=None)
        self.assertIn("answer", house)

    # ---- the dog count --------------------------------------------------------------------------

    def create(self, user, name, free):
        spec = spec_dict(name=name)
        return self.create_api.create_hound(self.create_api.CreateHoundRequest(spec=spec), current_user=user, _rl=None)

    def test_a_free_account_creating_a_second_dog_is_a_402_and_the_first_is_untouched(self):
        self.create(self.c.free, "Alpha Dog", True)
        self.assert_upgrade(self.refusal(self.create, self.c.free, "Bravo Dog", True), "more_dogs")
        mine = self.create_api.my_hounds(current_user=self.c.free)
        self.assertEqual(len(mine["hounds"]), 1)
        self.assertEqual((mine["plan"], mine["limit_running"]), ("free", 1))

    def test_a_paid_account_creates_five_and_sees_a_limit_of_five(self):
        for w in WORDS[:4]:                                   # the fixture's owner already has "Dog Days"
            self.create(self.c.owner, f"{w} Pack", False)
        self.assertEqual(self.refusal(self.create, self.c.owner, "Fargo Pack", False).status_code, 409)
        mine = self.create_api.my_hounds(current_user=self.c.owner)
        self.assertEqual((mine["plan"], mine["limit_running"]), ("paid", 5))

    def test_a_comp_may_add_a_second_dog(self):
        from src.appstate import comps
        self.create(self.c.free, "Alpha Dog", True)
        comps.grant_comp(user_id=self.c.free.id, reason="owner comp", db=self.c.db)
        self.assertEqual(self.create(self.c.free, "Bravo Dog", False)["hound"]["status"], "running")

    def test_a_grandfathered_free_account_keeps_all_its_dogs_in_the_list(self):
        for w in WORDS[:3]:                        # made before the rule, straight into the store
            user_store.create_hound(self.c.free.id, spec_dict(name=f"{w} Dog"))
        mine = self.create_api.my_hounds(current_user=self.c.free)
        self.assertEqual(len(mine["hounds"]), 3)
        self.assert_upgrade(self.refusal(self.create, self.c.free, "Delta Dog", True), "more_dogs")


if __name__ == "__main__":
    unittest.main()
